from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "data_governance_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.core.models import ContactStatus, MemoryKind, Message, Speaker, utc_now_iso
from whochat.services.bootstrap import build_services


def main() -> int:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("Governance Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, remark="keep this profile")
    services.contacts.add_alias(contact.id, "Gov Alias", "verify")
    services.messages.add_message(
        Message(
            id="governance_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="Exportable chat text.",
            content_type="text",
            ocr_confidence=0.92,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="governance_message_fp",
            source="verify",
        )
    )
    services.memories.add_pending(contact.id, MemoryKind.FACT, "Exportable memory.", 0.8)
    services.generation_logs.append(
        contact_id=contact.id,
        strategy_id=contact.strategy_id,
        provider="OpenAI-compatible",
        model="test-model",
        allowed=True,
        status="generated sk-generation-status-secret-value",
        suggestion_count=2,
        risk_summary="No key or prompt body is stored. Bearer generationBearerSecret12345",
        context_hash="a" * 64,
        page_type="chat_dm",
        page_confidence=0.9,
        message_count=1,
        memory_count=1,
    )

    export_path = services.governance.export_contact(contact.id)
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    if payload["contact"]["id"] != contact.id:
        raise RuntimeError("exported contact id mismatch")
    if {alias["alias"] for alias in payload["aliases"]} != {"Governance Contact", "Gov Alias"}:
        raise RuntimeError(f"exported aliases mismatch: {payload['aliases']}")
    if len(payload["messages"]) != 1 or len(payload["memories"]) != 1 or len(payload["generation_logs"]) != 1:
        raise RuntimeError("export did not include contact-scoped data")
    serialized = json.dumps(payload, ensure_ascii=False)
    for raw in ["sk-generation-status-secret-value", "generationBearerSecret12345", "api_key"]:
        if raw in serialized:
            raise RuntimeError(f"export leaked metadata secret: {raw}")
    if "[已脱敏:密钥]" not in serialized or "[已脱敏:Bearer]" not in serialized:
        raise RuntimeError("export did not redact generation log metadata")

    result = services.governance.clear_contact_data(contact.id)
    if result.messages_deleted != 1 or result.memories_deleted != 1 or result.generation_logs_deleted != 1:
        raise RuntimeError(f"unexpected clear result: {result}")
    refreshed = services.contacts.get(contact.id)
    if refreshed is None or refreshed.remark != "keep this profile":
        raise RuntimeError("clear should keep contact profile shell")
    if {alias.alias for alias in services.contacts.list_aliases(contact.id)} != {"Governance Contact", "Gov Alias"}:
        raise RuntimeError("clear should keep aliases")
    if services.messages.list_for_contact(contact.id) or services.memories.list_for_contact(contact.id):
        raise RuntimeError("messages or memories were not cleared")
    if services.generation_logs.list_for_contact(contact.id):
        raise RuntimeError("generation logs were not cleared")

    print(f"export={export_path} cleared_messages={result.messages_deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
