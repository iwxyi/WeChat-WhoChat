from __future__ import annotations

import io
import json
import os
import shutil
import sys
import urllib.error
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "ai_provider_diagnostics_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

import whochat.ai.generator as generator_module
from whochat.ai.generator import ReplyGenerator
from whochat.ai.models import ReplyContext
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services


class FakeResponse:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def main() -> int:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("AI Diagnostics Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, allow_cloud_ai=True)
    services.messages.add_message(
        Message(
            id="ai_provider_diag_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="请确认合同编号 123456789012345，不要泄露 sk-very-secret-token-value。",
            content_type="text",
            ocr_confidence=0.95,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="ai_provider_diag_fp",
            source="verify",
        )
    )
    context = ReplyContext(
        runtime=replace(missing_runtime_state(), page=PageClassification(PageType.CHAT_DM, 0.95, "verify")),
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=[],
    )
    config = AppConfig()
    config.ai.provider = "OpenAI Compatible"
    config.ai.base_url = "https://api.example.test/v1"
    config.ai.api_key = "sk-test-value-that-must-not-appear"
    config.privacy.trim_context_for_cloud = True

    original_urlopen = generator_module.urllib.request.urlopen
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            content = json.dumps(
                {"suggestions": [{"label": "稳妥", "text": "我确认后回复你。", "risk": "low", "rationale": "verify"}]},
                ensure_ascii=False,
            )
            return FakeResponse({"choices": [{"message": {"content": content}}]})
        if calls["count"] == 2:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"rate limit","prompt":"should not be logged fully"}'),
            )
        return FakeResponse({"not_choices": []})

    generator_module.urllib.request.urlopen = fake_urlopen
    try:
        ok = ReplyGenerator().generate(context, config)
        http_error = ReplyGenerator().generate(context, config)
        bad_shape = ReplyGenerator().generate(context, config)
    finally:
        generator_module.urllib.request.urlopen = original_urlopen

    if not ok.allowed or http_error.allowed or bad_shape.allowed:
        raise RuntimeError(f"unexpected provider results: {ok}, {http_error}, {bad_shape}")
    log_path = DATA_DIR / "logs" / "ai_provider.log"
    text = log_path.read_text(encoding="utf-8")
    for forbidden in ["sk-test-value", "sk-very-secret", "123456789012345", "合同编号"]:
        if forbidden in text:
            raise RuntimeError(f"provider diagnostics leaked sensitive content: {forbidden}")
    for expected in ["status=http_ok", "status=parsed", "status=http_error:429", "status=bad_content_json"]:
        if expected not in text:
            raise RuntimeError(f"provider diagnostics missing status {expected}: {text}")
    print(f"calls={calls['count']} log_chars={len(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
