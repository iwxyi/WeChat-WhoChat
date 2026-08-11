from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "provider_health_persistence_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.ai.models import ReplyContext, ReplyGenerationResult, ReplySuggestion
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services
from whochat.services.provider_health import ProviderHealthStore, provider_health_snapshot
from whochat.services.reply import ReplyGenerationService


class StaticGenerator:
    def __init__(self, result: ReplyGenerationResult) -> None:
        self.result = result
        self.calls = 0

    def generate(self, context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
        self.calls += 1
        return self.result


def main() -> int:
    services = build_services()
    context = _context(services)
    config = _cloud_config()
    config.ai.request_cooldown_seconds = 0
    config.ai.dedupe_context_minutes = 0
    config.ai.failure_backoff_threshold = 1
    config.ai.failure_backoff_minutes = 30

    failing_generator = StaticGenerator(ReplyGenerationResult(False, "AI 请求失败：verify", [], config.ai.provider))
    failing_service = ReplyGenerationService(services.generation_logs, failing_generator)
    failed = failing_service.generate(context, config)
    if failed.allowed or failing_service.provider_health_status != "backoff":
        raise RuntimeError(f"provider should enter backoff: {failing_service.provider_health_summary()}")
    health_file = DATA_DIR / "state" / "ai_provider_health.json"
    if not health_file.exists() or "backoff" not in health_file.read_text(encoding="utf-8"):
        raise RuntimeError("provider health backoff was not persisted")

    ok_generator = StaticGenerator(
        ReplyGenerationResult(
            True,
            "ai_generated",
            [ReplySuggestion("稳妥版", "我确认后回复你。", "low", "verify")],
            config.ai.provider,
        )
    )
    restored = ReplyGenerationService(services.generation_logs, ok_generator)
    blocked = restored.generate(context, config)
    if ok_generator.calls != 0:
        raise RuntimeError("restored backoff should block provider call before generator")
    if blocked.allowed or "provider_backoff" not in blocked.status:
        raise RuntimeError(f"restored service did not honor persisted backoff: {blocked.status}")

    restored.reset_provider_health("verify_persistence_reset")
    recovered = restored.generate(context, config)
    if not recovered.allowed or ok_generator.calls != 1:
        raise RuntimeError(f"manual reset should allow provider call: {recovered.status}, calls={ok_generator.calls}")
    if "healthy" not in health_file.read_text(encoding="utf-8"):
        raise RuntimeError("manual reset did not persist healthy state")
    expired_store = ProviderHealthStore(health_file)
    expired_store.save(provider_health_snapshot("backoff", 2, datetime.now(timezone.utc) - timedelta(seconds=1)))
    expired_service = ReplyGenerationService(services.generation_logs, ok_generator)
    expired_summary = expired_service.refresh_provider_health()
    if "status=recovering" not in expired_summary or expired_service.provider_backoff_until is not None:
        raise RuntimeError(f"expired backoff should become recovering: {expired_summary}")
    if "recovering" not in health_file.read_text(encoding="utf-8"):
        raise RuntimeError("expired backoff refresh was not persisted")
    print(f"persisted={health_file} calls={ok_generator.calls} health={restored.provider_health_summary()}")
    return 0


def _context(services) -> ReplyContext:
    contact = services.contacts.create_or_get_by_display_name("Provider Persistence Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, allow_cloud_ai=True)
    services.messages.add_message(
        Message(
            id="provider_persistence_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="请确认一下。",
            content_type="text",
            ocr_confidence=0.95,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="provider_persistence_fp",
            source="verify",
        )
    )
    return ReplyContext(
        runtime=replace(missing_runtime_state(), page=PageClassification(PageType.CHAT_DM, 0.91, "verify")),
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=[],
    )


def _cloud_config() -> AppConfig:
    config = AppConfig()
    config.ai.provider = "OpenAI Compatible"
    config.ai.api_key = "sk-test-value-that-must-not-be-used"
    return config


if __name__ == "__main__":
    raise SystemExit(main())
