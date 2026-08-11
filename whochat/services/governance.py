from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from whochat.core.models import Contact, utc_now_iso
from whochat.core.paths import app_data_dir
from whochat.security.redaction import redact_diagnostics_payload
from whochat.storage.repositories import (
    ContactRepository,
    GenerationLogRepository,
    LogRepository,
    MemoryRepository,
    MessageRepository,
    ReplyFeedbackRepository,
)
from whochat.storage.database import Database


@dataclass(frozen=True)
class ContactClearResult:
    contact: Contact
    messages_deleted: int
    memories_deleted: int
    generation_logs_deleted: int
    reply_feedback_deleted: int


@dataclass(frozen=True)
class GlobalClearResult:
    contacts_deleted: int
    messages_deleted: int
    memories_deleted: int
    generation_logs_deleted: int
    reply_feedback_deleted: int
    people_deleted: int
    group_members_deleted: int


class DataGovernanceService:
    def __init__(
        self,
        contacts: ContactRepository,
        messages: MessageRepository,
        memories: MemoryRepository,
        generation_logs: GenerationLogRepository,
        reply_feedback: ReplyFeedbackRepository,
        logs: LogRepository,
        db: Database | None = None,
    ) -> None:
        self.contacts = contacts
        self.messages = messages
        self.memories = memories
        self.generation_logs = generation_logs
        self.reply_feedback = reply_feedback
        self.logs = logs
        self.db = db or logs.db

    def export_contact(self, contact_id: str, output_dir: Path | None = None) -> Path:
        contact = self.contacts.get(contact_id)
        if contact is None:
            raise ValueError(f"contact not found: {contact_id}")

        export_dir = output_dir or app_data_dir() / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{_safe_filename(contact.display_name)}-{contact.id}-{utc_now_iso().replace(':', '-')}.json"
        path = export_dir / filename
        payload = {
            "export": {
                "app": "WhoChat",
                "schema_version": 1,
                "exported_at": utc_now_iso(),
                "scope": "contact",
                "redaction": "generation audit excludes API keys and full prompt payloads",
            },
            "contact": _serialize(contact),
            "aliases": _serialize(self.contacts.list_aliases(contact.id)),
            "messages": _serialize(self.messages.list_for_contact(contact.id, 10000)),
            "memories": _serialize(self.memories.list_for_contact(contact.id)),
            "generation_logs": _serialize(_redact_metadata_rows(self.generation_logs.list_for_contact(contact.id, 10000))),
            "reply_feedback": _serialize(_redact_metadata_rows(self.reply_feedback.list_for_contact(contact.id, 10000))),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logs.append(
            "info",
            "governance",
            "contact_exported",
            "Contact data exported",
            {"contact_id": contact.id, "path": str(path)},
        )
        return path

    def clear_contact_data(self, contact_id: str) -> ContactClearResult:
        contact = self.contacts.get(contact_id)
        if contact is None:
            raise ValueError(f"contact not found: {contact_id}")

        generation_count = self.generation_logs.delete_for_contact(contact.id)
        feedback_count = self.reply_feedback.delete_for_contact(contact.id)
        memory_count = self.memories.delete_for_contact(contact.id)
        message_count = self.messages.delete_for_contact(contact.id)
        refreshed = self.contacts.get(contact.id)
        if refreshed is None:
            raise ValueError(f"contact disappeared while clearing data: {contact.id}")
        result = ContactClearResult(
            contact=refreshed,
            messages_deleted=message_count,
            memories_deleted=memory_count,
            generation_logs_deleted=generation_count,
            reply_feedback_deleted=feedback_count,
        )
        self.logs.append(
            "warning",
            "governance",
            "contact_content_cleared",
            "Contact messages, memories and generation audits cleared",
            {
                "contact_id": contact.id,
                "messages_deleted": message_count,
                "memories_deleted": memory_count,
                "generation_logs_deleted": generation_count,
                "reply_feedback_deleted": feedback_count,
            },
        )
        return result

    def export_all(self, output_dir: Path | None = None) -> Path:
        export_dir = output_dir or app_data_dir() / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"whochat-all-{utc_now_iso().replace(':', '-')}.json"
        payload = {
            "export": {
                "app": "WhoChat",
                "schema_version": 1,
                "exported_at": utc_now_iso(),
                "scope": "all",
                "redaction": "API keys and full prompt payloads are not stored in audit tables",
            },
            "strategies": _serialize(self._table_rows("strategies")),
            "contacts": _serialize(self._table_rows("contacts")),
            "contact_aliases": _serialize(self._table_rows("contact_aliases")),
            "people": _serialize(self._table_rows("people")),
            "person_aliases": _serialize(self._table_rows("person_aliases")),
            "contact_person_links": _serialize(self._table_rows("contact_person_links")),
            "group_members": _serialize(self._table_rows("group_members")),
            "messages": _serialize(self._table_rows("messages")),
            "memories": _serialize(self._table_rows("memories")),
            "generation_logs": _serialize(_redact_metadata_rows(self._table_rows("generation_logs"))),
            "reply_feedback": _serialize(_redact_metadata_rows(self._table_rows("reply_feedback"))),
            "capture_samples": _serialize(self._table_rows("capture_samples")),
            "settings_audit": _serialize(_redact_settings_audit_rows(self._table_rows("settings_audit"))),
            "layout_calibrations": _serialize(self._table_rows("layout_calibrations")),
            "app_logs": _serialize(_redact_metadata_rows(self._table_rows("app_logs", limit=1000))),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logs.append("info", "governance", "global_exported", "Global data exported", {"path": str(path)})
        return path

    def clear_all_content(self) -> GlobalClearResult:
        with self.db.connect() as conn:
            counts = {
                "reply_feedback": _count_table(conn, "reply_feedback"),
                "generation_logs": _count_table(conn, "generation_logs"),
                "capture_samples": _count_table(conn, "capture_samples"),
                "memories": _count_table(conn, "memories"),
                "messages": _count_table(conn, "messages"),
                "group_members": _count_table(conn, "group_members"),
                "contact_person_links": _count_table(conn, "contact_person_links"),
                "person_aliases": _count_table(conn, "person_aliases"),
                "people": _count_table(conn, "people"),
                "contact_aliases": _count_table(conn, "contact_aliases"),
                "contacts": _count_table(conn, "contacts"),
            }
            for table in [
                "reply_feedback",
                "generation_logs",
                "capture_samples",
                "memories",
                "messages",
                "group_members",
                "contact_person_links",
                "person_aliases",
                "people",
                "contact_aliases",
                "contacts",
            ]:
                conn.execute(f"DELETE FROM {table}")
        result = GlobalClearResult(
            contacts_deleted=counts["contacts"],
            messages_deleted=counts["messages"],
            memories_deleted=counts["memories"],
            generation_logs_deleted=counts["generation_logs"],
            reply_feedback_deleted=counts["reply_feedback"],
            people_deleted=counts["people"],
            group_members_deleted=counts["group_members"],
        )
        self.logs.append(
            "warning",
            "governance",
            "global_content_cleared",
            "All contacts, identities, messages, memories and generation audits cleared",
            asdict(result),
        )
        return result

    def _table_rows(self, table: str, limit: int | None = None) -> list[dict]:
        query = f"SELECT * FROM {table}"
        params: tuple = ()
        if limit is not None:
            query += " ORDER BY rowid DESC LIMIT ?"
            params = (limit,)
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def _serialize(value: Any) -> Any:
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, Enum):
        return value.value
    return value


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value.strip())
    return cleaned[:40] or "contact"


def _count_table(conn, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"]) if row else 0


def _redact_settings_audit_rows(rows: list[dict]) -> list[dict]:
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        changes_json = str(item.get("changes_json", "{}"))
        try:
            changes = json.loads(changes_json)
        except json.JSONDecodeError:
            changes = {}
        if "ai.api_key" in changes:
            changes["ai.secret"] = changes.pop("ai.api_key")
        item["changes_json"] = json.dumps(changes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        result.append(item)
    return result


def _redact_metadata_rows(rows: list[Any]) -> list[Any]:
    return [_neutralize_sensitive_key_names(redact_diagnostics_payload(_serialize(row))) for row in rows]


def _neutralize_sensitive_key_names(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"(?i)api[_-]?key", "secret", value)
    if isinstance(value, list):
        return [_neutralize_sensitive_key_names(item) for item in value]
    if isinstance(value, dict):
        return {
            re.sub(r"(?i)api[_-]?key", "secret", str(key)): _neutralize_sensitive_key_names(item)
            for key, item in value.items()
        }
    return value
