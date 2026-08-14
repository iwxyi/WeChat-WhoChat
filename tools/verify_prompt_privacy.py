from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "prompt_privacy_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

import whochat.ai.generator as generator_module
from whochat.ai.generator import ReplyGenerator
from whochat.ai.models import ReplyContext
from whochat.ai.prompt import build_prompt_preview
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, MemoryKind, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "suggestions": [
                                        {
                                            "label": "稳妥版",
                                            "text": "我确认后回复你。",
                                            "risk": "low",
                                            "rationale": "verify",
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")


def main() -> int:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("Prompt Privacy Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, allow_cloud_ai=True)
    services.messages.add_message(
        Message(
            id="prompt_privacy_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="我的手机号是 13812345678，邮箱 user@example.com，链接 https://example.com/a?b=1，订单 123456789012345。",
            content_type="text",
            ocr_confidence=0.94,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="prompt_privacy_fp",
            source="verify",
        )
    )
    services.memories.add_pending(contact.id, MemoryKind.FACT, "对方提到密钥 sk-very-secret-token-value。", 0.9)
    context = ReplyContext(
        runtime=replace(missing_runtime_state(), page=PageClassification(PageType.CHAT_DM, 0.92, "verify")),
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=services.memories.list_for_contact(contact.id),
    )
    config = AppConfig()
    config.ai.provider = "OpenAI Compatible"
    config.ai.api_key = "sk-test-value-that-must-not-be-used"
    config.privacy.trim_context_for_cloud = True

    preview = build_prompt_preview(context, config)
    combined = preview.combined_text
    if "JSON" not in preview.user_prompt:
        raise RuntimeError("cloud user prompt must explicitly request JSON for compatible providers")
    for raw in ["13812345678", "user@example.com", "https://example.com", "123456789012345", "sk-very-secret-token-value"]:
        if raw in combined:
            raise RuntimeError(f"preview leaked sensitive text: {raw}")
    for marker in ["[已脱敏:手机号]", "[已脱敏:邮箱]", "[已脱敏:链接]", "[已脱敏:长数字]", "[已脱敏:密钥]"]:
        if marker not in combined:
            raise RuntimeError(f"preview missing redaction marker: {marker}")

    captured: dict[str, str] = {}
    original_urlopen = generator_module.urllib.request.urlopen

    def fake_urlopen(request, timeout):
        captured["payload"] = request.data.decode("utf-8")
        captured["timeout"] = str(timeout)
        return FakeResponse()

    generator_module.urllib.request.urlopen = fake_urlopen
    try:
        result = ReplyGenerator().generate(context, config)
    finally:
        generator_module.urllib.request.urlopen = original_urlopen
    if not result.allowed:
        raise RuntimeError(f"fake provider should return suggestions: {result.status}")
    payload = captured.get("payload", "")
    for raw in ["13812345678", "user@example.com", "https://example.com", "123456789012345", "sk-very-secret-token-value"]:
        if raw in payload:
            raise RuntimeError(f"provider payload leaked sensitive text: {raw}")
    print(f"redaction={preview.redaction_summary} payload_chars={len(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
