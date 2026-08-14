from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "ai_request_policy_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.ai.models import ReplyContext, ReplyGenerationResult, ReplySuggestion
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services
from whochat.services.reply import ReplyGenerationService


class CountingGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
        self.calls += 1
        return ReplyGenerationResult(
            True,
            "ai_generated",
            [ReplySuggestion("稳妥版", "收到，我确认后回复。", "low", "verify")],
            config.ai.provider,
        )


def main() -> int:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("Policy Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, allow_cloud_ai=True)
    services.messages.add_message(
        Message(
            id="policy_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="请确认一下今天的安排。",
            content_type="text",
            ocr_confidence=0.93,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="policy_message_fp",
            source="verify",
        )
    )
    runtime = replace(missing_runtime_state(), page=PageClassification(PageType.CHAT_DM, 0.91, "verify"))
    context = ReplyContext(
        runtime=runtime,
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=[],
    )

    duplicate_config = _cloud_config()
    duplicate_config.ai.request_cooldown_seconds = 0
    duplicate_config.ai.dedupe_context_minutes = 30
    duplicate_config.ai.max_daily_cloud_requests = 100
    duplicate_generator = CountingGenerator()
    duplicate_service = ReplyGenerationService(services.generation_logs, duplicate_generator)
    first = duplicate_service.generate(context, duplicate_config)
    duplicate = duplicate_service.generate(context, duplicate_config)
    if not first.allowed or not duplicate.allowed or duplicate.status != "ai_cached:unchanged_context":
        raise RuntimeError(f"duplicate policy failed: first={first.status} duplicate={duplicate.status}")
    if duplicate.suggestions != first.suggestions:
        raise RuntimeError("duplicate policy should retain the first successful suggestions")
    if duplicate_generator.calls != 1:
        raise RuntimeError(f"duplicate policy should avoid generator call, calls={duplicate_generator.calls}")

    cooldown_config = _cloud_config()
    cooldown_config.ai.request_cooldown_seconds = 60
    cooldown_config.ai.dedupe_context_minutes = 0
    cooldown_config.ai.max_daily_cloud_requests = 100
    cooldown_generator = CountingGenerator()
    cooldown_service = ReplyGenerationService(services.generation_logs, cooldown_generator)
    first = cooldown_service.generate(context, cooldown_config)
    cooldown = cooldown_service.generate(context, cooldown_config)
    if not first.allowed or not cooldown.allowed or cooldown.status != "ai_cached:unchanged_context":
        raise RuntimeError(f"cooldown policy failed: first={first.status} cooldown={cooldown.status}")
    if cooldown_generator.calls != 1:
        raise RuntimeError(f"cooldown policy should avoid generator call, calls={cooldown_generator.calls}")

    daily_config = _cloud_config()
    daily_config.ai.request_cooldown_seconds = 0
    daily_config.ai.dedupe_context_minutes = 0
    daily_config.ai.max_daily_cloud_requests = services.generation_logs.count_cloud_attempts_since("0001-01-01T00:00:00+00:00")
    daily_generator = CountingGenerator()
    daily_service = ReplyGenerationService(services.generation_logs, daily_generator)
    daily = daily_service.generate(context, daily_config)
    if daily.allowed or "daily_limit" not in daily.status:
        raise RuntimeError(f"daily limit policy failed: {daily.status}")
    if daily_generator.calls != 0:
        raise RuntimeError(f"daily policy should avoid generator call, calls={daily_generator.calls}")

    audits = services.generation_logs.tail(10)
    if not any(row.status == "ai_cached:unchanged_context" for row in audits):
        raise RuntimeError("cached duplicate result was not audited")
    if not any(row.status.startswith("blocked:daily_limit") for row in audits):
        raise RuntimeError("daily limit block was not audited")
    print(f"cloud_calls={duplicate_generator.calls + cooldown_generator.calls + daily_generator.calls} audits={len(audits)}")
    return 0


def _cloud_config() -> AppConfig:
    config = AppConfig()
    config.ai.provider = "OpenAI Compatible"
    config.ai.api_key = "sk-test-value-that-must-not-be-used"
    return config


if __name__ == "__main__":
    raise SystemExit(main())
