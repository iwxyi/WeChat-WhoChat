from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone

from whochat.ai.generator import ReplyGenerator
from whochat.ai.models import ReplyContext, ReplyGenerationResult
from whochat.config import AppConfig
from whochat.core.models import ContactStatus
from whochat.core.runtime import PageType
from whochat.diagnostics import append_diagnostics_log
from whochat.services.provider_health import ProviderHealthStore, provider_health_snapshot
from whochat.storage.repositories import GenerationLogRepository


class ReplyGenerationService:
    def __init__(
        self,
        audit_logs: GenerationLogRepository,
        generator: ReplyGenerator | None = None,
        health_store: ProviderHealthStore | None = None,
    ) -> None:
        self.audit_logs = audit_logs
        self.generator = generator or ReplyGenerator()
        self.health_store = health_store or ProviderHealthStore()
        self.last_audit_id: str | None = None
        self._last_cloud_attempt_at: datetime | None = None
        snapshot = self.health_store.load()
        self.consecutive_cloud_failures = snapshot.consecutive_failures
        self.provider_backoff_until = _parse_ts(snapshot.backoff_until) if snapshot.backoff_until else None
        self.provider_health_status = snapshot.status or "healthy"

    def generate(self, context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
        digest = context_hash(context)
        cloud_may_attempt = _cloud_request_may_be_attempted(context, config)
        result = self._blocked_by_request_policy(digest, config) if cloud_may_attempt else None
        if result is None:
            if cloud_may_attempt:
                self._last_cloud_attempt_at = datetime.now(timezone.utc)
            result = self.generator.generate(context, config)
            if cloud_may_attempt:
                self._apply_provider_health(result, config)
        audit = self.audit_logs.append(
            contact_id=context.contact.id if context.contact else None,
            strategy_id=context.strategy.id if context.strategy else None,
            provider=result.provider,
            model=config.ai.model if config.ai.provider != "Disabled" else "",
            allowed=result.allowed,
            status=result.status,
            suggestion_count=len(result.suggestions),
            risk_summary=_risk_summary(result),
            context_hash=digest,
            page_type=context.runtime.page.page_type.value,
            page_confidence=context.runtime.page.confidence,
            message_count=len(context.messages),
            memory_count=len(context.memories),
        )
        self.last_audit_id = audit.id
        return result

    def _blocked_by_request_policy(self, digest: str, config: AppConfig) -> ReplyGenerationResult | None:
        now = datetime.now(timezone.utc)
        self.refresh_provider_health(now)
        if self.provider_backoff_until and now < self.provider_backoff_until:
            return ReplyGenerationResult(False, "blocked:provider_backoff: AI Provider 连续失败，退避中", [], config.ai.provider)

        cooldown = max(0, config.ai.request_cooldown_seconds)
        if self._last_cloud_attempt_at and (now - self._last_cloud_attempt_at).total_seconds() < cooldown:
            return ReplyGenerationResult(False, "blocked:cooldown: 云端 AI 请求过于频繁，已暂缓", [], config.ai.provider)

        dedupe_minutes = max(0, config.ai.dedupe_context_minutes)
        if dedupe_minutes:
            latest = self.audit_logs.latest_for_context(digest)
            if latest and latest.provider in {"OpenAI", "OpenAI Compatible"} and not latest.status.startswith("blocked:"):
                latest_at = _parse_ts(latest.ts)
                if latest_at and now - latest_at < timedelta(minutes=dedupe_minutes):
                    return ReplyGenerationResult(False, "blocked:duplicate_context: 相同上下文近期已经请求过云端 AI", [], config.ai.provider)

        daily_limit = max(0, config.ai.max_daily_cloud_requests)
        if daily_limit:
            day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc).isoformat()
            used = self.audit_logs.count_cloud_attempts_since(day_start)
            if used >= daily_limit:
                return ReplyGenerationResult(False, "blocked:daily_limit: 今日云端 AI 请求已达到上限", [], config.ai.provider)
        return None

    def _apply_provider_health(self, result: ReplyGenerationResult, config: AppConfig) -> None:
        if result.allowed:
            self.consecutive_cloud_failures = 0
            self.provider_backoff_until = None
            self.provider_health_status = "healthy"
            self._persist_provider_health()
            return
        if result.status.startswith("blocked:"):
            return
        self.consecutive_cloud_failures += 1
        threshold = max(1, config.ai.failure_backoff_threshold)
        if self.consecutive_cloud_failures >= threshold:
            minutes = max(0, config.ai.failure_backoff_minutes)
            self.provider_backoff_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            self.provider_health_status = "backoff"
        else:
            self.provider_health_status = f"degraded:{self.consecutive_cloud_failures}/{threshold}"
        self._persist_provider_health()

    def provider_health_summary(self) -> str:
        until = self.provider_backoff_until.isoformat() if self.provider_backoff_until else "-"
        return (
            f"status={self.provider_health_status} "
            f"failures={self.consecutive_cloud_failures} "
            f"backoff_until={until}"
        )

    def refresh_provider_health(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        if self.provider_backoff_until and now >= self.provider_backoff_until:
            before = self.provider_health_summary()
            self.provider_backoff_until = None
            self.provider_health_status = "recovering"
            self._persist_provider_health()
            after = self.provider_health_summary()
            append_diagnostics_log("ai_provider", f"provider_health_recovering before={before} after={after}")
        return self.provider_health_summary()

    def reset_provider_health(self, reason: str = "manual") -> str:
        before = self.provider_health_summary()
        self.consecutive_cloud_failures = 0
        self.provider_backoff_until = None
        self.provider_health_status = "healthy"
        self._persist_provider_health()
        after = self.provider_health_summary()
        append_diagnostics_log("ai_provider", f"provider_health_reset reason={reason} before={before} after={after}")
        return after

    def _persist_provider_health(self) -> None:
        snapshot = provider_health_snapshot(
            self.provider_health_status,
            self.consecutive_cloud_failures,
            self.provider_backoff_until,
        )
        self.health_store.save(snapshot)


def context_hash(context: ReplyContext) -> str:
    payload = {
        "contact_id": context.contact.id if context.contact else None,
        "strategy_id": context.strategy.id if context.strategy else None,
        "page_type": context.runtime.page.page_type.value,
        "messages": [
            {
                "speaker": message.speaker.value,
                "fingerprint": message.fingerprint,
                "observed_at": message.observed_at,
                "partial": message.partial,
            }
            for message in context.messages[-30:]
        ],
        "memories": [
            {
                "id": memory.id,
                "status": memory.status.value,
                "kind": memory.kind.value,
                "updated_at": memory.updated_at,
            }
            for memory in context.memories[:30]
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _cloud_request_may_be_attempted(context: ReplyContext, config: AppConfig) -> bool:
    if config.ai.provider not in {"OpenAI", "OpenAI Compatible"} or not config.ai.api_key:
        return False
    if config.privacy.manual_protection_blocks_replies and context.strategy and context.strategy.requires_manual_reply:
        return False
    if config.capture.pause_ai_on_unknown_page and context.runtime.page.page_type not in {PageType.CHAT_DM, PageType.CHAT_GROUP}:
        return False
    if context.contact is None or not context.contact.allow_cloud_ai:
        return False
    if context.contact.status in {ContactStatus.IGNORED, ContactStatus.MERGED} or context.contact.merged_into:
        return False
    return True


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _risk_summary(result: ReplyGenerationResult) -> str:
    if not result.suggestions:
        return ""
    risks: dict[str, int] = {}
    for suggestion in result.suggestions:
        risks[suggestion.risk] = risks.get(suggestion.risk, 0) + 1
    return ",".join(f"{risk}:{count}" for risk, count in sorted(risks.items()))
