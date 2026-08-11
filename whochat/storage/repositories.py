from __future__ import annotations

import json
import uuid
from dataclasses import asdict, replace

from whochat.core.models import (
    AppLog,
    CaptureSample,
    Contact,
    ContactAlias,
    ContactPersonLink,
    ContactStatus,
    ConversationType,
    GroupMember,
    IdentityStatus,
    GenerationLog,
    Memory,
    MemoryKind,
    MemoryStatus,
    Message,
    Person,
    PersonAlias,
    ReplyFeedback,
    SettingsAudit,
    Speaker,
    Strategy,
    utc_now_iso,
)
from whochat.core.runtime import LayoutCalibration, RelativeRect, TargetApp, ThemeMode
from whochat.storage.database import Database


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class StrategyRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_defaults(self) -> None:
        now = utc_now_iso()
        defaults = [
            Strategy("default", "默认", "根据上下文给出自然、稳妥的回复建议", "默认", "自然、清晰", "", "稳妥版,简短版,推进版", False, now, now),
            Strategy("leader_boundary", "领导-保持边界", "清楚表达进度和边界，避免过度承诺", "保持边界", "尊重、简洁、事实导向", "抱怨,甩锅,阴阳怪气", "稳妥版,简短版,边界版", False, now, now),
            Strategy("client", "客户", "推进下一步并降低不确定感", "推进", "专业、明确、有耐心", "过度承诺,模糊时间", "稳妥版,推进版,解释版", False, now, now),
            Strategy("manual_protect", "手动回复保护", "只整理信息，不主动代写", "保护", "用户亲自回复", "代写亲密关系回复", "", True, now, now),
        ]
        with self.db.connect() as conn:
            for item in defaults:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO strategies
                    (id, name, goal, mode, tone, avoid, reply_variants, requires_manual_reply, created_at, updated_at)
                    VALUES (:id, :name, :goal, :mode, :tone, :avoid, :reply_variants, :requires_manual_reply, :created_at, :updated_at)
                    """,
                    {**asdict(item), "requires_manual_reply": int(item.requires_manual_reply)},
                )

    def list_all(self, include_archived: bool = True) -> list[Strategy]:
        with self.db.connect() as conn:
            where = "" if include_archived else "WHERE archived = 0"
            rows = conn.execute(
                f"SELECT * FROM strategies {where} ORDER BY archived, requires_manual_reply, name"
            ).fetchall()
        return [_strategy_from_row(row) for row in rows]

    def list_active(self) -> list[Strategy]:
        return self.list_all(include_archived=False)

    def get(self, strategy_id: str) -> Strategy | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
        return _strategy_from_row(row) if row else None

    def create(
        self,
        name: str,
        goal: str,
        mode: str,
        tone: str,
        avoid: str = "",
        reply_variants: str = "",
        requires_manual_reply: bool = False,
    ) -> Strategy:
        now = utc_now_iso()
        strategy = Strategy(
            id=new_id("strategy"),
            name=name,
            goal=goal,
            mode=mode,
            tone=tone,
            avoid=avoid,
            reply_variants=reply_variants,
            requires_manual_reply=requires_manual_reply,
            created_at=now,
            updated_at=now,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO strategies
                (id, name, goal, mode, tone, avoid, reply_variants, requires_manual_reply, created_at, updated_at)
                VALUES (:id, :name, :goal, :mode, :tone, :avoid, :reply_variants, :requires_manual_reply, :created_at, :updated_at)
                """,
                {**asdict(strategy), "requires_manual_reply": int(strategy.requires_manual_reply)},
            )
        return strategy

    def update(self, strategy: Strategy) -> Strategy:
        updated = Strategy(**{**asdict(strategy), "updated_at": utc_now_iso()})
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE strategies
                SET name = :name,
                    goal = :goal,
                    mode = :mode,
                    tone = :tone,
                    avoid = :avoid,
                    reply_variants = :reply_variants,
                    requires_manual_reply = :requires_manual_reply,
                    archived = :archived,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                {
                    **asdict(updated),
                    "requires_manual_reply": int(updated.requires_manual_reply),
                    "archived": int(updated.archived),
                },
            )
        return updated

    def set_archived(self, strategy_id: str, archived: bool) -> Strategy:
        current = self.get(strategy_id)
        if current is None:
            raise ValueError(f"strategy not found: {strategy_id}")
        if strategy_id in {"default", "manual_protect"} and archived:
            raise ValueError("built-in safety strategies cannot be archived")
        updated = Strategy(**{**asdict(current), "archived": archived, "updated_at": utc_now_iso()})
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE strategies SET archived = ?, updated_at = ? WHERE id = ?",
                (int(archived), updated.updated_at, strategy_id),
            )
        return updated

    def count_assigned_contacts(self, strategy_id: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM contacts WHERE strategy_id = ?", (strategy_id,)).fetchone()
        return int(row["count"]) if row else 0


class ContactRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_or_get_by_display_name(
        self,
        display_name: str,
        platform: str = "wechat",
        conversation_type: ConversationType = ConversationType.UNKNOWN,
        strategy_id: str = "default",
    ) -> Contact:
        with self.db.connect() as conn:
            existing = conn.execute(
                """
                SELECT contacts.* FROM contacts
                LEFT JOIN contact_aliases ON contact_aliases.contact_id = contacts.id
                WHERE contacts.platform = ?
                  AND contacts.merged_into IS NULL
                  AND (contacts.display_name = ? OR contact_aliases.alias = ?)
                ORDER BY contacts.created_at LIMIT 1
                """,
                (platform, display_name, display_name),
            ).fetchone()
            if existing:
                return _contact_from_row(existing)
            now = utc_now_iso()
            contact = Contact(
                id=new_id("contact"),
                platform=platform,
                display_name=display_name,
                conversation_type=conversation_type,
                status=ContactStatus.UNCONFIRMED,
                strategy_id=strategy_id,
                allow_cloud_ai=False,
                remark="",
                avatar_fingerprint="",
                merged_into=None,
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                """
                INSERT INTO contacts
                (id, platform, display_name, conversation_type, status, strategy_id, allow_cloud_ai, remark, avatar_fingerprint, merged_into, created_at, updated_at)
                VALUES (:id, :platform, :display_name, :conversation_type, :status, :strategy_id, :allow_cloud_ai, :remark, :avatar_fingerprint, :merged_into, :created_at, :updated_at)
                """,
                _contact_params(contact),
            )
            conn.execute(
                "INSERT INTO contact_aliases(id, contact_id, alias, source, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("alias"), contact.id, display_name, "display_name", now),
            )
            return contact

    def list_recent(self, limit: int = 100, include_merged: bool = False) -> list[Contact]:
        with self.db.connect() as conn:
            where = "" if include_merged else "WHERE merged_into IS NULL"
            rows = conn.execute(f"SELECT * FROM contacts {where} ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [_contact_from_row(row) for row in rows]

    def get(self, contact_id: str) -> Contact | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return _contact_from_row(row) if row else None

    def update_profile(
        self,
        contact_id: str,
        *,
        display_name: str | None = None,
        status: ContactStatus | None = None,
        strategy_id: str | None = None,
        allow_cloud_ai: bool | None = None,
        remark: str | None = None,
    ) -> Contact:
        current = self.get(contact_id)
        if current is None:
            raise ValueError(f"contact not found: {contact_id}")
        updated = Contact(
            id=current.id,
            platform=current.platform,
            display_name=display_name if display_name is not None else current.display_name,
            conversation_type=current.conversation_type,
            status=status if status is not None else current.status,
            strategy_id=strategy_id if strategy_id is not None else current.strategy_id,
            allow_cloud_ai=allow_cloud_ai if allow_cloud_ai is not None else current.allow_cloud_ai,
            remark=remark if remark is not None else current.remark,
            avatar_fingerprint=current.avatar_fingerprint,
            merged_into=current.merged_into,
            created_at=current.created_at,
            updated_at=utc_now_iso(),
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE contacts
                SET display_name = :display_name,
                    status = :status,
                    strategy_id = :strategy_id,
                    allow_cloud_ai = :allow_cloud_ai,
                    remark = :remark,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                _contact_params(updated),
            )
        return updated

    def list_aliases(self, contact_id: str) -> list[ContactAlias]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM contact_aliases WHERE contact_id = ? ORDER BY created_at",
                (contact_id,),
            ).fetchall()
        return [ContactAlias(**dict(row)) for row in rows]

    def add_alias(self, contact_id: str, alias: str, source: str = "manual") -> ContactAlias | None:
        alias = alias.strip()
        if not alias:
            return None
        if self.get(contact_id) is None:
            raise ValueError(f"contact not found: {contact_id}")
        now = utc_now_iso()
        item = ContactAlias(new_id("alias"), contact_id, alias, source, now)
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO contact_aliases(id, contact_id, alias, source, created_at)
                VALUES (:id, :contact_id, :alias, :source, :created_at)
                """,
                asdict(item),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT * FROM contact_aliases WHERE contact_id = ? AND alias = ?",
                    (contact_id, alias),
                ).fetchone()
                return ContactAlias(**dict(row)) if row else None
        return item

    def merge_contacts(self, source_id: str, target_id: str) -> Contact:
        if source_id == target_id:
            raise ValueError("cannot merge contact into itself")
        source = self.get(source_id)
        target = self.get(target_id)
        if source is None or target is None:
            raise ValueError("source or target contact not found")
        if source.merged_into or source.status == ContactStatus.MERGED:
            raise ValueError("source contact has already been merged")
        if target.merged_into or target.status == ContactStatus.MERGED:
            raise ValueError("target contact cannot be a merged contact")
        if source.platform != target.platform:
            raise ValueError("cannot merge contacts from different platforms")

        now = utc_now_iso()
        with self.db.connect() as conn:
            conn.execute(
                """
                DELETE FROM messages
                WHERE contact_id = ?
                  AND fingerprint IN (SELECT fingerprint FROM messages WHERE contact_id = ?)
                """,
                (source_id, target_id),
            )
            conn.execute("UPDATE messages SET contact_id = ? WHERE contact_id = ?", (target_id, source_id))
            conn.execute("UPDATE memories SET contact_id = ?, updated_at = ? WHERE contact_id = ?", (target_id, now, source_id))
            conn.execute("UPDATE generation_logs SET contact_id = ? WHERE contact_id = ?", (target_id, source_id))
            conn.execute(
                """
                INSERT OR IGNORE INTO contact_aliases(id, contact_id, alias, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id("alias"), target_id, source.display_name, "merged_display_name", now),
            )
            for row in conn.execute("SELECT alias, source FROM contact_aliases WHERE contact_id = ?", (source_id,)):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO contact_aliases(id, contact_id, alias, source, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (new_id("alias"), target_id, row["alias"], f"merged:{row['source']}", now),
                )
            conn.execute("DELETE FROM contact_aliases WHERE contact_id = ?", (source_id,))
            conn.execute(
                """
                UPDATE contacts
                SET status = ?, merged_into = ?, updated_at = ?
                WHERE id = ?
                """,
                (ContactStatus.MERGED.value, target_id, now, source_id),
            )
            conn.execute("UPDATE contacts SET updated_at = ? WHERE id = ?", (now, target_id))
        refreshed = self.get(target_id)
        if refreshed is None:
            raise ValueError(f"target contact not found after merge: {target_id}")
        return refreshed


class IdentityRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_person(self, display_name: str, source: str = "manual", status: IdentityStatus = IdentityStatus.SUSPECTED) -> Person:
        now = utc_now_iso()
        person = Person(
            id=new_id("person"),
            display_name=display_name.strip(),
            status=status,
            remark="",
            created_at=now,
            updated_at=now,
        )
        if not person.display_name:
            raise ValueError("person display name cannot be empty")
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO people(id, display_name, status, remark, created_at, updated_at)
                VALUES (:id, :display_name, :status, :remark, :created_at, :updated_at)
                """,
                _person_params(person),
            )
            conn.execute(
                "INSERT OR IGNORE INTO person_aliases(id, person_id, alias, source, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("person_alias"), person.id, person.display_name, source, now),
            )
        return person

    def get_person(self, person_id: str) -> Person | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
        return _person_from_row(row) if row else None

    def find_people_by_alias(self, alias: str) -> list[Person]:
        alias = alias.strip()
        if not alias:
            return []
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT people.* FROM people
                LEFT JOIN person_aliases ON person_aliases.person_id = people.id
                WHERE people.display_name = ? OR person_aliases.alias = ?
                ORDER BY people.updated_at DESC
                """,
                (alias, alias),
            ).fetchall()
        return [_person_from_row(row) for row in rows]

    def add_person_alias(self, person_id: str, alias: str, source: str = "manual") -> PersonAlias | None:
        alias = alias.strip()
        if not alias:
            return None
        if self.get_person(person_id) is None:
            raise ValueError(f"person not found: {person_id}")
        now = utc_now_iso()
        item = PersonAlias(new_id("person_alias"), person_id, alias, source, now)
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO person_aliases(id, person_id, alias, source, created_at)
                VALUES (:id, :person_id, :alias, :source, :created_at)
                """,
                asdict(item),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT * FROM person_aliases WHERE person_id = ? AND alias = ?",
                    (person_id, alias),
                ).fetchone()
                return PersonAlias(**dict(row)) if row else None
        return item

    def list_person_aliases(self, person_id: str) -> list[PersonAlias]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM person_aliases WHERE person_id = ? ORDER BY created_at",
                (person_id,),
            ).fetchall()
        return [PersonAlias(**dict(row)) for row in rows]

    def link_contact_to_person(
        self,
        contact_id: str,
        person_id: str,
        *,
        confidence: float,
        source: str,
        verified: bool = False,
    ) -> ContactPersonLink:
        now = utc_now_iso()
        link = ContactPersonLink(
            id=new_id("contact_person"),
            contact_id=contact_id,
            person_id=person_id,
            confidence=max(0.0, min(confidence, 1.0)),
            source=source,
            verified=verified,
            created_at=now,
            updated_at=now,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO contact_person_links(id, contact_id, person_id, confidence, source, verified, created_at, updated_at)
                VALUES (:id, :contact_id, :person_id, :confidence, :source, :verified, :created_at, :updated_at)
                ON CONFLICT(contact_id, person_id) DO UPDATE SET
                    confidence = excluded.confidence,
                    source = excluded.source,
                    verified = excluded.verified,
                    updated_at = excluded.updated_at
                """,
                _contact_person_link_params(link),
            )
            row = conn.execute(
                """
                SELECT * FROM contact_person_links
                WHERE contact_id = ? AND person_id = ?
                """,
                (contact_id, person_id),
            ).fetchone()
        return _contact_person_link_from_row(row)

    def list_people_for_contact(self, contact_id: str) -> list[tuple[Person, ContactPersonLink]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT people.*, contact_person_links.id AS link_id,
                       contact_person_links.contact_id AS link_contact_id,
                       contact_person_links.person_id AS link_person_id,
                       contact_person_links.confidence AS link_confidence,
                       contact_person_links.source AS link_source,
                       contact_person_links.verified AS link_verified,
                       contact_person_links.created_at AS link_created_at,
                       contact_person_links.updated_at AS link_updated_at
                FROM contact_person_links
                JOIN people ON people.id = contact_person_links.person_id
                WHERE contact_person_links.contact_id = ?
                ORDER BY contact_person_links.verified DESC, contact_person_links.confidence DESC
                """,
                (contact_id,),
            ).fetchall()
        return [(_person_from_row(row), _contact_person_link_from_joined_row(row)) for row in rows]

    def add_group_member(
        self,
        *,
        group_contact_id: str,
        member_display_name: str,
        person_id: str | None = None,
        platform_contact_id: str | None = None,
        confidence: float = 0.5,
        source: str = "ocr",
    ) -> GroupMember:
        now = utc_now_iso()
        item = GroupMember(
            id=new_id("group_member"),
            group_contact_id=group_contact_id,
            member_display_name=member_display_name.strip(),
            person_id=person_id,
            platform_contact_id=platform_contact_id,
            confidence=max(0.0, min(confidence, 1.0)),
            source=source,
            created_at=now,
            updated_at=now,
        )
        if not item.member_display_name:
            raise ValueError("group member display name cannot be empty")
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO group_members
                (id, group_contact_id, member_display_name, person_id, platform_contact_id, confidence, source, created_at, updated_at)
                VALUES
                (:id, :group_contact_id, :member_display_name, :person_id, :platform_contact_id, :confidence, :source, :created_at, :updated_at)
                ON CONFLICT(group_contact_id, member_display_name) DO UPDATE SET
                    person_id = excluded.person_id,
                    platform_contact_id = excluded.platform_contact_id,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                _group_member_params(item),
            )
            row = conn.execute(
                "SELECT * FROM group_members WHERE group_contact_id = ? AND member_display_name = ?",
                (group_contact_id, item.member_display_name),
            ).fetchone()
        return _group_member_from_row(row)

    def list_group_members(self, group_contact_id: str) -> list[GroupMember]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM group_members WHERE group_contact_id = ? ORDER BY member_display_name",
                (group_contact_id,),
            ).fetchall()
        return [_group_member_from_row(row) for row in rows]


class MessageRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add_message(self, message: Message) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO messages
                (id, contact_id, speaker, text, content_type, ocr_confidence, observed_at, message_time, time_source, partial, fingerprint, source)
                VALUES (:id, :contact_id, :speaker, :text, :content_type, :ocr_confidence, :observed_at, :message_time, :time_source, :partial, :fingerprint, :source)
                """,
                _message_params(message),
            )
            return cursor.rowcount > 0

    def list_for_contact(self, contact_id: str, limit: int = 200) -> list[Message]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE contact_id = ? ORDER BY observed_at DESC LIMIT ?",
                (contact_id, limit),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def delete_for_contact(self, contact_id: str) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE contact_id = ?", (contact_id,))
            return cursor.rowcount


class MemoryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add_pending(self, contact_id: str, kind: MemoryKind, content: str, confidence: float | None = None) -> Memory:
        now = utc_now_iso()
        memory = Memory(
            id=new_id("memory"),
            contact_id=contact_id,
            kind=kind,
            status=MemoryStatus.PENDING,
            content=content,
            confidence=confidence,
            source_message_id=None,
            expires_at=None,
            created_at=now,
            updated_at=now,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories
                (id, contact_id, kind, status, content, confidence, source_message_id, expires_at, created_at, updated_at)
                VALUES (:id, :contact_id, :kind, :status, :content, :confidence, :source_message_id, :expires_at, :created_at, :updated_at)
                """,
                _memory_params(memory),
            )
        return memory

    def list_for_contact(self, contact_id: str) -> list[Memory]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE contact_id = ? ORDER BY created_at DESC",
                (contact_id,),
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def delete_for_contact(self, contact_id: str) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE contact_id = ?", (contact_id,))
            return cursor.rowcount

    def list_by_status(self, status: MemoryStatus, limit: int = 200) -> list[Memory]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status.value, limit),
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def update_status(self, memory_id: str, status: MemoryStatus) -> Memory:
        now = utc_now_iso()
        with self.db.connect() as conn:
            conn.execute("UPDATE memories SET status = ?, updated_at = ? WHERE id = ?", (status.value, now, memory_id))
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise ValueError(f"memory not found: {memory_id}")
        return _memory_from_row(row)


class LogRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(self, level: str, module: str, event: str, message: str, context: dict | None = None) -> AppLog:
        log = AppLog(
            id=new_id("log"),
            ts=utc_now_iso(),
            level=level,
            module=module,
            event=event,
            message=message,
            context_json=json.dumps(context or {}, ensure_ascii=False),
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_logs(id, ts, level, module, event, message, context_json)
                VALUES (:id, :ts, :level, :module, :event, :message, :context_json)
                """,
                asdict(log),
            )
        return log

    def tail(self, limit: int = 200) -> list[AppLog]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM app_logs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [AppLog(**dict(row)) for row in rows]


class GenerationLogRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        *,
        contact_id: str | None,
        strategy_id: str | None,
        provider: str,
        model: str,
        allowed: bool,
        status: str,
        suggestion_count: int,
        risk_summary: str,
        context_hash: str,
        page_type: str,
        page_confidence: float,
        message_count: int,
        memory_count: int,
    ) -> GenerationLog:
        log = GenerationLog(
            id=new_id("generation"),
            ts=utc_now_iso(),
            contact_id=contact_id,
            strategy_id=strategy_id,
            provider=provider,
            model=model,
            allowed=allowed,
            status=status,
            suggestion_count=suggestion_count,
            risk_summary=risk_summary,
            context_hash=context_hash,
            page_type=page_type,
            page_confidence=page_confidence,
            message_count=message_count,
            memory_count=memory_count,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO generation_logs
                (id, ts, contact_id, strategy_id, provider, model, allowed, status, suggestion_count,
                 risk_summary, context_hash, page_type, page_confidence, message_count, memory_count)
                VALUES
                (:id, :ts, :contact_id, :strategy_id, :provider, :model, :allowed, :status, :suggestion_count,
                 :risk_summary, :context_hash, :page_type, :page_confidence, :message_count, :memory_count)
                """,
                _generation_log_params(log),
            )
        return log

    def tail(self, limit: int = 100) -> list[GenerationLog]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM generation_logs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [_generation_log_from_row(row) for row in rows]

    def list_for_contact(self, contact_id: str, limit: int = 500) -> list[GenerationLog]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM generation_logs WHERE contact_id = ? ORDER BY ts DESC LIMIT ?",
                (contact_id, limit),
            ).fetchall()
        return [_generation_log_from_row(row) for row in rows]

    def latest_for_context(self, context_hash: str) -> GenerationLog | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM generation_logs WHERE context_hash = ? ORDER BY ts DESC LIMIT 1",
                (context_hash,),
            ).fetchone()
        return _generation_log_from_row(row) if row else None

    def count_cloud_attempts_since(self, since_iso: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM generation_logs
                WHERE ts >= ?
                  AND provider IN ('OpenAI', 'OpenAI Compatible')
                  AND status NOT LIKE 'blocked:%'
                """,
                (since_iso,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def delete_for_contact(self, contact_id: str) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM generation_logs WHERE contact_id = ?", (contact_id,))
            return cursor.rowcount


class ReplyFeedbackRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        *,
        contact_id: str | None,
        strategy_id: str | None,
        provider: str,
        status: str,
        suggestion_label: str,
        suggestion_text: str,
        risk: str,
        feedback: str,
        context_hash: str,
        page_type: str,
        message_count: int,
        memory_count: int,
    ) -> ReplyFeedback:
        record = ReplyFeedback(
            id=new_id("reply_feedback"),
            ts=utc_now_iso(),
            contact_id=contact_id,
            strategy_id=strategy_id,
            provider=provider,
            status=status,
            suggestion_label=suggestion_label[:48],
            suggestion_text_preview=_preview_text(suggestion_text, 96),
            risk=risk[:24],
            feedback=feedback[:24],
            context_hash=context_hash,
            page_type=page_type,
            message_count=message_count,
            memory_count=memory_count,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO reply_feedback
                (id, ts, contact_id, strategy_id, provider, status, suggestion_label, suggestion_text_preview,
                 risk, feedback, context_hash, page_type, message_count, memory_count)
                VALUES
                (:id, :ts, :contact_id, :strategy_id, :provider, :status, :suggestion_label, :suggestion_text_preview,
                 :risk, :feedback, :context_hash, :page_type, :message_count, :memory_count)
                """,
                asdict(record),
            )
        return record

    def tail(self, limit: int = 100) -> list[ReplyFeedback]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM reply_feedback ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [ReplyFeedback(**dict(row)) for row in rows]

    def list_for_contact(self, contact_id: str, limit: int = 500) -> list[ReplyFeedback]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reply_feedback WHERE contact_id = ? ORDER BY ts DESC LIMIT ?",
                (contact_id, limit),
            ).fetchall()
        return [ReplyFeedback(**dict(row)) for row in rows]

    def delete_for_contact(self, contact_id: str) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM reply_feedback WHERE contact_id = ?", (contact_id,))
            return cursor.rowcount

    def delete_older_than(self, cutoff_iso: str) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM reply_feedback WHERE ts < ?", (cutoff_iso,))
            return cursor.rowcount


class SettingsAuditRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(self, *, actor: str, scope: str, changes: dict, secret_backend: str) -> SettingsAudit:
        audit = SettingsAudit(
            id=new_id("settings_audit"),
            ts=utc_now_iso(),
            actor=actor,
            scope=scope,
            changes_json=json.dumps(changes, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            secret_backend=secret_backend,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings_audit(id, ts, actor, scope, changes_json, secret_backend)
                VALUES (:id, :ts, :actor, :scope, :changes_json, :secret_backend)
                """,
                asdict(audit),
            )
        return audit

    def tail(self, limit: int = 100) -> list[SettingsAudit]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM settings_audit ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [SettingsAudit(**dict(row)) for row in rows]


class CaptureSampleRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        *,
        job_id: int,
        hwnd: int | None,
        target_app: str,
        app_label: str,
        snapshot_hash: str,
        image_path: str,
        ocr_image_path: str,
        crop_rect_json: str,
        ocr_engine: str,
        ocr_warning: str,
        page_type: str,
        page_confidence: float,
        message_count: int,
        retained_image: bool,
        title_ocr_image_path: str = "",
        title_crop_rect_json: str = "",
        title_ocr_elapsed_ms: int | None = None,
        content_ocr_elapsed_ms: int | None = None,
        total_elapsed_ms: int | None = None,
    ) -> CaptureSample:
        sample = CaptureSample(
            id=new_id("capture"),
            ts=utc_now_iso(),
            job_id=job_id,
            hwnd=hwnd,
            target_app=target_app,
            app_label=app_label,
            snapshot_hash=snapshot_hash,
            image_path=image_path,
            ocr_image_path=ocr_image_path,
            crop_rect_json=crop_rect_json,
            title_ocr_image_path=title_ocr_image_path,
            title_crop_rect_json=title_crop_rect_json,
            title_ocr_elapsed_ms=title_ocr_elapsed_ms,
            content_ocr_elapsed_ms=content_ocr_elapsed_ms,
            total_elapsed_ms=total_elapsed_ms,
            ocr_engine=ocr_engine,
            ocr_warning=ocr_warning,
            page_type=page_type,
            page_confidence=page_confidence,
            message_count=message_count,
            retained_image=retained_image,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO capture_samples
                (id, ts, job_id, hwnd, target_app, app_label, snapshot_hash, image_path, ocr_image_path, crop_rect_json,
                 title_ocr_image_path, title_crop_rect_json, title_ocr_elapsed_ms, content_ocr_elapsed_ms, total_elapsed_ms,
                 ocr_engine, ocr_warning, page_type, page_confidence, message_count, retained_image)
                VALUES
                (:id, :ts, :job_id, :hwnd, :target_app, :app_label, :snapshot_hash, :image_path, :ocr_image_path, :crop_rect_json,
                 :title_ocr_image_path, :title_crop_rect_json, :title_ocr_elapsed_ms, :content_ocr_elapsed_ms, :total_elapsed_ms,
                 :ocr_engine, :ocr_warning, :page_type, :page_confidence, :message_count, :retained_image)
                """,
                _capture_sample_params(sample),
            )
        return sample

    def tail(self, limit: int = 100) -> list[CaptureSample]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM capture_samples ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [_capture_sample_from_row(row) for row in rows]

    def delete_all(self) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM capture_samples")
            return cursor.rowcount


class CalibrationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_active(self, target: TargetApp = TargetApp.WECHAT) -> LayoutCalibration | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM layout_calibrations WHERE target = ? AND active = 1 ORDER BY updated_at DESC LIMIT 1",
                (target.value,),
            ).fetchone()
        return _calibration_from_row(row) if row else None

    def list_all(self, target: TargetApp = TargetApp.WECHAT) -> list[LayoutCalibration]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM layout_calibrations WHERE target = ? ORDER BY active DESC, updated_at DESC",
                (target.value,),
            ).fetchall()
        return [_calibration_from_row(row) for row in rows]

    def save(self, calibration: LayoutCalibration) -> LayoutCalibration:
        updated = replace(calibration, updated_at=utc_now_iso())
        with self.db.connect() as conn:
            if updated.active:
                conn.execute("UPDATE layout_calibrations SET active = 0 WHERE target = ?", (updated.target.value,))
            conn.execute(
                """
                INSERT INTO layout_calibrations
                (id, target, name, theme, dpi_scale, nav_rect_json, chat_list_rect_json, content_rect_json,
                 title_rect_json, message_rect_json, input_rect_json, active, created_at, updated_at)
                VALUES
                (:id, :target, :name, :theme, :dpi_scale, :nav_rect_json, :chat_list_rect_json, :content_rect_json,
                 :title_rect_json, :message_rect_json, :input_rect_json, :active, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    theme = excluded.theme,
                    dpi_scale = excluded.dpi_scale,
                    nav_rect_json = excluded.nav_rect_json,
                    chat_list_rect_json = excluded.chat_list_rect_json,
                    content_rect_json = excluded.content_rect_json,
                    title_rect_json = excluded.title_rect_json,
                    message_rect_json = excluded.message_rect_json,
                    input_rect_json = excluded.input_rect_json,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                _calibration_params(updated),
            )
        return updated

    def create_from_layout(
        self,
        *,
        name: str,
        target: TargetApp,
        window_rect,
        layout,
        theme: ThemeMode = ThemeMode.UNKNOWN,
        dpi_scale: float = 1.0,
        active: bool = True,
    ) -> LayoutCalibration:
        now = utc_now_iso()
        calibration = LayoutCalibration(
            id=new_id("calibration"),
            target=target,
            name=name,
            theme=theme,
            dpi_scale=dpi_scale,
            nav_rect=RelativeRect.from_absolute(window_rect, layout.nav_rect),
            chat_list_rect=RelativeRect.from_absolute(window_rect, layout.chat_list_rect),
            content_rect=RelativeRect.from_absolute(window_rect, layout.content_rect),
            title_rect=RelativeRect.from_absolute(window_rect, layout.title_rect),
            message_rect=RelativeRect.from_absolute(window_rect, layout.message_rect),
            input_rect=RelativeRect.from_absolute(window_rect, layout.input_rect),
            active=active,
            created_at=now,
            updated_at=now,
        )
        return self.save(calibration)


def _strategy_from_row(row) -> Strategy:
    data = dict(row)
    data["requires_manual_reply"] = bool(data["requires_manual_reply"])
    data["archived"] = bool(data.get("archived", 0))
    return Strategy(**data)


def _contact_from_row(row) -> Contact:
    data = dict(row)
    data["conversation_type"] = ConversationType(data["conversation_type"])
    data["status"] = ContactStatus(data["status"])
    data["allow_cloud_ai"] = bool(data["allow_cloud_ai"])
    return Contact(**data)


def _person_from_row(row) -> Person:
    data = dict(row)
    data["status"] = IdentityStatus(data["status"])
    return Person(
        id=data["id"],
        display_name=data["display_name"],
        status=data["status"],
        remark=data["remark"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _contact_person_link_from_row(row) -> ContactPersonLink:
    data = dict(row)
    data["verified"] = bool(data["verified"])
    return ContactPersonLink(**data)


def _contact_person_link_from_joined_row(row) -> ContactPersonLink:
    return ContactPersonLink(
        id=row["link_id"],
        contact_id=row["link_contact_id"],
        person_id=row["link_person_id"],
        confidence=float(row["link_confidence"]),
        source=row["link_source"],
        verified=bool(row["link_verified"]),
        created_at=row["link_created_at"],
        updated_at=row["link_updated_at"],
    )


def _group_member_from_row(row) -> GroupMember:
    data = dict(row)
    return GroupMember(
        id=data["id"],
        group_contact_id=data["group_contact_id"],
        member_display_name=data["member_display_name"],
        person_id=data["person_id"],
        platform_contact_id=data["platform_contact_id"],
        confidence=float(data["confidence"]),
        source=data["source"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _message_from_row(row) -> Message:
    data = dict(row)
    data["speaker"] = Speaker(data["speaker"])
    data["partial"] = bool(data["partial"])
    return Message(**data)


def _memory_from_row(row) -> Memory:
    data = dict(row)
    data["kind"] = MemoryKind(data["kind"])
    data["status"] = MemoryStatus(data["status"])
    return Memory(**data)


def _generation_log_from_row(row) -> GenerationLog:
    data = dict(row)
    data["allowed"] = bool(data["allowed"])
    return GenerationLog(**data)


def _capture_sample_from_row(row) -> CaptureSample:
    data = dict(row)
    data["retained_image"] = bool(data["retained_image"])
    return CaptureSample(**data)


def _contact_params(contact: Contact) -> dict:
    data = asdict(contact)
    data["conversation_type"] = contact.conversation_type.value
    data["status"] = contact.status.value
    data["allow_cloud_ai"] = int(contact.allow_cloud_ai)
    return data


def _person_params(person: Person) -> dict:
    data = asdict(person)
    data["status"] = person.status.value
    return data


def _contact_person_link_params(link: ContactPersonLink) -> dict:
    data = asdict(link)
    data["verified"] = int(link.verified)
    return data


def _group_member_params(member: GroupMember) -> dict:
    return asdict(member)


def _message_params(message: Message) -> dict:
    data = asdict(message)
    data["speaker"] = message.speaker.value
    data["partial"] = int(message.partial)
    return data


def _memory_params(memory: Memory) -> dict:
    data = asdict(memory)
    data["kind"] = memory.kind.value
    data["status"] = memory.status.value
    return data


def _generation_log_params(log: GenerationLog) -> dict:
    data = asdict(log)
    data["allowed"] = int(log.allowed)
    return data


def _preview_text(value: str, limit: int) -> str:
    text = " ".join(value.strip().split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _capture_sample_params(sample: CaptureSample) -> dict:
    data = asdict(sample)
    data["retained_image"] = int(sample.retained_image)
    return data


def _calibration_from_row(row) -> LayoutCalibration:
    data = dict(row)
    return LayoutCalibration(
        id=data["id"],
        target=TargetApp(data["target"]),
        name=data["name"],
        theme=ThemeMode(data["theme"]),
        dpi_scale=float(data["dpi_scale"]),
        nav_rect=_relative_rect_from_json(data["nav_rect_json"]),
        chat_list_rect=_relative_rect_from_json(data["chat_list_rect_json"]),
        content_rect=_relative_rect_from_json(data["content_rect_json"]),
        title_rect=_relative_rect_from_json(data["title_rect_json"]),
        message_rect=_relative_rect_from_json(data["message_rect_json"]),
        input_rect=_relative_rect_from_json(data["input_rect_json"]),
        active=bool(data["active"]),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _calibration_params(calibration: LayoutCalibration) -> dict:
    return {
        "id": calibration.id,
        "target": calibration.target.value,
        "name": calibration.name,
        "theme": calibration.theme.value,
        "dpi_scale": calibration.dpi_scale,
        "nav_rect_json": _relative_rect_to_json(calibration.nav_rect),
        "chat_list_rect_json": _relative_rect_to_json(calibration.chat_list_rect),
        "content_rect_json": _relative_rect_to_json(calibration.content_rect),
        "title_rect_json": _relative_rect_to_json(calibration.title_rect),
        "message_rect_json": _relative_rect_to_json(calibration.message_rect),
        "input_rect_json": _relative_rect_to_json(calibration.input_rect),
        "active": int(calibration.active),
        "created_at": calibration.created_at,
        "updated_at": calibration.updated_at,
    }


def _relative_rect_from_json(value: str) -> RelativeRect:
    data = json.loads(value)
    return RelativeRect(float(data["left"]), float(data["top"]), float(data["right"]), float(data["bottom"])).clamp()


def _relative_rect_to_json(value: RelativeRect) -> str:
    rect = value.clamp()
    return json.dumps(asdict(rect), ensure_ascii=False, separators=(",", ":"))
