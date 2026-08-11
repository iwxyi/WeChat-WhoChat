from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "contact_merge_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.config import AppConfig
from whochat.ai.models import ReplyContext
from whochat.core.models import ContactStatus, MemoryKind, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services


def main() -> int:
    services = build_services()
    target = services.contacts.create_or_get_by_display_name("Alice")
    source = services.contacts.create_or_get_by_display_name("Alice Work")
    target = services.contacts.update_profile(target.id, status=ContactStatus.CONFIRMED, remark="target remark")
    source = services.contacts.update_profile(source.id, status=ContactStatus.SUSPECTED, remark="source remark")
    services.contacts.add_alias(source.id, "A. Work", "verify")

    now = utc_now_iso()
    services.messages.add_message(_message("target_message", target.id, "shared_fp", "target text", now))
    services.messages.add_message(_message("source_duplicate", source.id, "shared_fp", "duplicate text", now))
    services.messages.add_message(_message("source_unique", source.id, "source_unique_fp", "source unique text", now))
    services.memories.add_pending(source.id, MemoryKind.FACT, "source memory should move", 0.8)

    runtime = missing_runtime_state()
    context = ReplyContext(
        runtime=runtime.__class__(
            window=runtime.window,
            layout=runtime.layout,
            page=PageClassification(PageType.CHAT_DM, 0.9, "verify"),
            capture_decision=runtime.capture_decision,
            paused=runtime.paused,
        ),
        contact=source,
        strategy=services.strategies.get(source.strategy_id),
        messages=services.messages.list_for_contact(source.id),
        memories=[],
    )
    services.reply_generator.generate(context, AppConfig())

    merged_target = services.contacts.merge_contacts(source.id, target.id)
    merged_source = services.contacts.get(source.id)
    if merged_source is None or merged_source.status != ContactStatus.MERGED or merged_source.merged_into != target.id:
        raise RuntimeError("source contact was not marked merged")
    aliases = {alias.alias for alias in services.contacts.list_aliases(target.id)}
    if not {"Alice Work", "A. Work"}.issubset(aliases):
        raise RuntimeError(f"merged aliases missing: {aliases}")
    messages = services.messages.list_for_contact(target.id, 20)
    if len(messages) != 2 or {message.fingerprint for message in messages} != {"shared_fp", "source_unique_fp"}:
        raise RuntimeError(f"message merge/dedup failed: {[(m.fingerprint, m.text) for m in messages]}")
    memories = services.memories.list_for_contact(target.id)
    if not any("source memory" in memory.content for memory in memories):
        raise RuntimeError("source memory was not moved")
    audits = services.generation_logs.tail(10)
    if not audits or audits[0].contact_id != target.id:
        raise RuntimeError("generation audit contact was not moved")
    visible = services.contacts.list_recent(20)
    if any(contact.id == source.id for contact in visible):
        raise RuntimeError("merged source should be hidden from recent contacts")

    print(f"target={merged_target.display_name} aliases={len(aliases)} messages={len(messages)} audits={len(audits)}")
    return 0


def _message(message_id: str, contact_id: str, fingerprint: str, text: str, observed_at: str) -> Message:
    return Message(
        id=message_id,
        contact_id=contact_id,
        speaker=Speaker.OTHER,
        text=text,
        content_type="text",
        ocr_confidence=0.9,
        observed_at=observed_at,
        message_time=None,
        time_source="observed",
        partial=False,
        fingerprint=fingerprint,
        source="verify",
    )


if __name__ == "__main__":
    raise SystemExit(main())
