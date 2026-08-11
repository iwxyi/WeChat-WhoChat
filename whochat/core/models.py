from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationType(StrEnum):
    DM = "dm"
    GROUP = "group"
    OFFICIAL = "official"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class ContactStatus(StrEnum):
    UNCONFIRMED = "unconfirmed"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    MERGED = "merged"
    IGNORED = "ignored"


class IdentityStatus(StrEnum):
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class Speaker(StrEnum):
    ME = "me"
    OTHER = "other"
    MEMBER = "member"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    AVOID = "avoid"
    TEMPORARY = "temporary"
    SUMMARY = "summary"


class MemoryStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    goal: str
    mode: str
    tone: str
    avoid: str
    reply_variants: str
    requires_manual_reply: bool
    created_at: str
    updated_at: str
    archived: bool = False


@dataclass(frozen=True)
class Contact:
    id: str
    platform: str
    display_name: str
    conversation_type: ConversationType
    status: ContactStatus
    strategy_id: str
    allow_cloud_ai: bool
    remark: str
    avatar_fingerprint: str
    merged_into: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ContactAlias:
    id: str
    contact_id: str
    alias: str
    source: str
    created_at: str


@dataclass(frozen=True)
class Person:
    id: str
    display_name: str
    status: IdentityStatus
    remark: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PersonAlias:
    id: str
    person_id: str
    alias: str
    source: str
    created_at: str


@dataclass(frozen=True)
class ContactPersonLink:
    id: str
    contact_id: str
    person_id: str
    confidence: float
    source: str
    verified: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GroupMember:
    id: str
    group_contact_id: str
    member_display_name: str
    person_id: str | None
    platform_contact_id: str | None
    confidence: float
    source: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: str
    contact_id: str
    speaker: Speaker
    text: str
    content_type: str
    ocr_confidence: float | None
    observed_at: str
    message_time: str | None
    time_source: str
    partial: bool
    fingerprint: str
    source: str
    sender_name: str = ""


@dataclass(frozen=True)
class Memory:
    id: str
    contact_id: str
    kind: MemoryKind
    status: MemoryStatus
    content: str
    confidence: float | None
    source_message_id: str | None
    expires_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AppLog:
    id: str
    ts: str
    level: str
    module: str
    event: str
    message: str
    context_json: str


@dataclass(frozen=True)
class GenerationLog:
    id: str
    ts: str
    contact_id: str | None
    strategy_id: str | None
    provider: str
    model: str
    allowed: bool
    status: str
    suggestion_count: int
    risk_summary: str
    context_hash: str
    page_type: str
    page_confidence: float
    message_count: int
    memory_count: int


@dataclass(frozen=True)
class ReplyFeedback:
    id: str
    ts: str
    contact_id: str | None
    strategy_id: str | None
    provider: str
    status: str
    suggestion_label: str
    suggestion_text_preview: str
    risk: str
    feedback: str
    context_hash: str
    page_type: str
    message_count: int
    memory_count: int


@dataclass(frozen=True)
class SettingsAudit:
    id: str
    ts: str
    actor: str
    scope: str
    changes_json: str
    secret_backend: str


@dataclass(frozen=True)
class CaptureSample:
    id: str
    ts: str
    job_id: int
    hwnd: int | None
    target_app: str
    app_label: str
    snapshot_hash: str
    image_path: str
    ocr_image_path: str
    crop_rect_json: str
    ocr_engine: str
    ocr_warning: str
    page_type: str
    page_confidence: float
    message_count: int
    retained_image: bool
    title_ocr_image_path: str = ""
    title_crop_rect_json: str = ""
    title_ocr_elapsed_ms: int | None = None
    content_ocr_elapsed_ms: int | None = None
    total_elapsed_ms: int | None = None
