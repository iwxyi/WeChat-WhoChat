from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "provider_health_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.ai.models import ReplyContext, ReplyGenerationResult, ReplySuggestion
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services
from whochat.services.reply import ReplyGenerationService


class FlakyGenerator:
    def __init__(self, results: list[ReplyGenerationResult]) -> None:
        self.results = results
        self.calls = 0

    def generate(self, context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return ReplyGenerationResult(False, "AI 请求失败：verify exhausted", [], config.ai.provider)


def main() -> int:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("Provider Health Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, allow_cloud_ai=True)
    services.messages.add_message(
        Message(
            id="provider_health_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="请帮我确认一下。",
            content_type="text",
            ocr_confidence=0.95,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="provider_health_fp",
            source="verify",
        )
    )
    context = ReplyContext(
        runtime=replace(missing_runtime_state(), page=PageClassification(PageType.CHAT_DM, 0.91, "verify")),
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=[],
    )
    config = _cloud_config()
    config.ai.request_cooldown_seconds = 0
    config.ai.dedupe_context_minutes = 0
    config.ai.max_daily_cloud_requests = 100
    config.ai.failure_backoff_threshold = 2
    config.ai.failure_backoff_minutes = 10
    failing = ReplyGenerationResult(False, "AI 请求失败：verify network", [], config.ai.provider)
    ok = ReplyGenerationResult(
        True,
        "ai_generated",
        [ReplySuggestion("稳妥版", "我确认后回复你。", "low", "verify")],
        config.ai.provider,
    )
    generator = FlakyGenerator([failing, failing, ok])
    service = ReplyGenerationService(services.generation_logs, generator)

    first = service.generate(context, config)
    second = service.generate(context, config)
    blocked = service.generate(context, config)
    if first.allowed or second.allowed:
        raise RuntimeError("first two provider attempts should fail")
    if generator.calls != 2:
        raise RuntimeError(f"backoff should block third provider call, calls={generator.calls}")
    if blocked.allowed or "provider_backoff" not in blocked.status:
        raise RuntimeError(f"expected provider backoff block, got {blocked.status}")
    if service.provider_health_status != "backoff" or service.provider_backoff_until is None:
        raise RuntimeError(f"provider health not in backoff: {service.provider_health_summary()}")

    reset_summary = service.reset_provider_health("verify_manual_reset")
    if "status=healthy" not in reset_summary or service.consecutive_cloud_failures != 0 or service.provider_backoff_until is not None:
        raise RuntimeError(f"manual reset did not restore health: {reset_summary}")
    recovered = service.generate(context, config)
    if not recovered.allowed or generator.calls != 3:
        raise RuntimeError(f"provider should recover after successful call: {recovered.status}, calls={generator.calls}")
    if service.provider_health_status != "healthy" or service.consecutive_cloud_failures != 0:
        raise RuntimeError(f"provider health should reset after success: {service.provider_health_summary()}")
    audits = services.generation_logs.tail(10)
    if not any(row.status.startswith("blocked:provider_backoff") for row in audits):
        raise RuntimeError("provider backoff block was not audited")
    print(f"calls={generator.calls} health={service.provider_health_summary()} audits={len(audits)} reset={reset_summary}")
    return 0


def _cloud_config() -> AppConfig:
    config = AppConfig()
    config.ai.provider = "OpenAI Compatible"
    config.ai.api_key = "sk-test-value-that-must-not-be-used"
    return config


if __name__ == "__main__":
    raise SystemExit(main())
