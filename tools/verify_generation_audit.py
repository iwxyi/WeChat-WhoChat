from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "generation_audit_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.ai.models import ReplyContext
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services


def main() -> int:
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("Audit Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    services.messages.add_message(
        Message(
            id="audit_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="Sensitive project content should not be stored in audit logs.",
            content_type="text",
            ocr_confidence=0.93,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="audit_message_fp",
            source="verify",
        )
    )
    runtime = replace(missing_runtime_state(), page=PageClassification(PageType.CHAT_DM, 0.9, "verify"))
    context = ReplyContext(
        runtime=runtime,
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=[],
    )
    config = AppConfig()
    config.ai.provider = "Local Model"
    config.ai.api_key = "sk-should-not-appear"
    allowed = services.reply_generator.generate(context, config)
    blocked = services.reply_generator.generate(replace(context, runtime=missing_runtime_state()), config)
    if not allowed.allowed or blocked.allowed:
        raise RuntimeError(f"unexpected generation results: allowed={allowed.allowed} blocked={blocked.allowed}")

    rows = services.generation_logs.tail(10)
    if len(rows) < 2:
        raise RuntimeError(f"expected at least 2 generation audit rows, got {len(rows)}")
    latest_text = "\n".join(str(row) for row in rows)
    if "sk-should-not-appear" in latest_text or "Sensitive project content" in latest_text:
        raise RuntimeError("generation audit leaked API key or full message text")
    if not any(row.allowed for row in rows) or not any(not row.allowed for row in rows):
        raise RuntimeError("generation audit did not capture both allowed and blocked attempts")
    if any(len(row.context_hash) != 64 for row in rows[:2]):
        raise RuntimeError("context hash should be sha256 hex")

    print(f"audits={len(rows)} latest_allowed={rows[0].allowed} hash={rows[0].context_hash[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
