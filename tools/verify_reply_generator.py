from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["WHOCHAT_DATA_DIR"] = str(ROOT / "tmp" / "reply_generator_verify")
os.environ["WHOCHAT_DB_PATH"] = str(ROOT / "tmp" / "reply_generator_verify" / "whochat.db")

import whochat.ai.generator as generator_module
from whochat.ai.generator import ReplyGenerator
from whochat.ai.models import ReplyContext
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services


def main() -> None:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("测试联系人")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    now = utc_now_iso()
    services.messages.add_message(
        Message(
            id="verify_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="下午前能确认方案吗？",
            content_type="text",
            ocr_confidence=0.94,
            observed_at=now,
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="verify_message",
            source="verify",
        )
    )
    runtime = replace(
        missing_runtime_state(),
        page=PageClassification(PageType.CHAT_DM, 0.92, "verify chat page"),
    )
    context = ReplyContext(
        runtime=runtime,
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=[],
    )
    result = ReplyGenerator().generate(context, AppConfig())
    assert result.allowed, result.status
    assert len(result.suggestions) == 3
    cloud_config = AppConfig()
    cloud_config.ai.api_key = "sk-test-value-that-must-not-be-used"
    cloud_blocked = ReplyGenerator().generate(context, cloud_config)
    assert not cloud_blocked.allowed
    assert "第三方 AI" in cloud_blocked.status
    network_called = False
    original_urlopen = generator_module.urllib.request.urlopen

    def fail_urlopen(*_args, **_kwargs):
        nonlocal network_called
        network_called = True
        raise RuntimeError("network must not be called for unknown contact")

    generator_module.urllib.request.urlopen = fail_urlopen
    try:
        unknown_contact_cloud = ReplyGenerator().generate(replace(context, contact=None, messages=[]), cloud_config)
    finally:
        generator_module.urllib.request.urlopen = original_urlopen
    assert not unknown_contact_cloud.allowed
    assert "聊天对象" in unknown_contact_cloud.status
    assert not network_called
    blocked = ReplyGenerator().generate(replace(context, runtime=missing_runtime_state()), AppConfig())
    assert not blocked.allowed
    print(
        f"allowed={result.allowed} suggestions={len(result.suggestions)} "
        f"cloud_blocked={cloud_blocked.status} unknown_cloud={unknown_contact_cloud.status} blocked={blocked.status}"
    )


if __name__ == "__main__":
    main()
