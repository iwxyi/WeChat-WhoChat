from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "global_governance_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.core.models import ContactStatus, ConversationType, IdentityStatus, MemoryKind, Message, Speaker, utc_now_iso
from whochat.services.bootstrap import build_services


def main() -> int:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("Global Gov Contact", platform="wechat")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    group = services.contacts.create_or_get_by_display_name("Global Gov Group", platform="wechat", conversation_type=ConversationType.GROUP)
    person = services.identities.create_person("Global Person", status=IdentityStatus.CONFIRMED)
    services.identities.link_contact_to_person(contact.id, person.id, confidence=1.0, source="verify", verified=True)
    services.identities.add_group_member(
        group_contact_id=group.id,
        member_display_name="Global Person",
        person_id=person.id,
        platform_contact_id=contact.id,
        confidence=1.0,
        source="verify",
    )
    services.messages.add_message(
        Message(
            id="global_gov_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="Global governance export text.",
            content_type="text",
            ocr_confidence=0.9,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="global_gov_fp",
            source="verify",
        )
    )
    services.memories.add_pending(contact.id, MemoryKind.FACT, "Global governance memory.", 0.8)
    services.generation_logs.append(
        contact_id=contact.id,
        strategy_id=contact.strategy_id,
        provider="OpenAI Compatible",
        model="test-model",
        allowed=True,
        status="generated sk-global-generation-secret-value",
        suggestion_count=1,
        risk_summary="low:1 Bearer globalBearerSecret12345",
        context_hash="b" * 64,
        page_type="chat_dm",
        page_confidence=0.9,
        message_count=1,
        memory_count=1,
    )
    services.settings_audit.append(
        actor="verify",
        scope="settings",
        changes={"ai.api_key": {"old": "<empty>", "new": "<set>", "changed": True}},
        secret_backend="verify",
    )
    services.logs.append(
        "error",
        "verify",
        "sensitive_log",
        "api_key=globalDiagnosticApiKeySecret12345 Authorization: Bearer globalDiagnosticBearerSecret12345 13812345678",
    )

    export_path = services.governance.export_all()
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    for key in ["contacts", "people", "group_members", "messages", "memories", "generation_logs", "settings_audit"]:
        if not payload.get(key):
            raise RuntimeError(f"global export missing {key}")
    serialized = json.dumps(payload, ensure_ascii=False)
    for raw in [
        "api_key",
        "sk-global-generation-secret-value",
        "globalBearerSecret12345",
        "globalDiagnosticApiKeySecret12345",
        "globalDiagnosticBearerSecret12345",
        "13812345678",
    ]:
        if raw in serialized:
            raise RuntimeError(f"global export leaked sensitive metadata: {raw}")
    for marker in ["[已脱敏:密钥]", "[已脱敏:Bearer]", "[已脱敏:API Key]", "[已脱敏:手机号]"]:
        if marker not in serialized:
            raise RuntimeError(f"global export missing redaction marker: {marker}")

    result = services.governance.clear_all_content()
    if result.contacts_deleted != 2 or result.messages_deleted != 1 or result.memories_deleted != 1:
        raise RuntimeError(f"unexpected clear result: {result}")
    if services.contacts.list_recent(10, include_merged=True):
        raise RuntimeError("contacts should be globally cleared")
    if services.identities.find_people_by_alias("Global Person"):
        raise RuntimeError("people should be globally cleared")
    if services.messages.list_for_contact(contact.id) or services.memories.list_for_contact(contact.id):
        raise RuntimeError("messages or memories should be globally cleared")
    if not services.strategies.list_all():
        raise RuntimeError("strategies should be retained")
    if not services.settings_audit.tail(10):
        raise RuntimeError("settings audit should be retained")

    print(f"export={export_path} contacts_deleted={result.contacts_deleted} settings_audits={len(services.settings_audit.tail(10))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
