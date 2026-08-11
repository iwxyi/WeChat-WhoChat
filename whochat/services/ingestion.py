from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from whochat.core.models import Contact, ContactStatus, ConversationType, Message, Speaker
from whochat.core.runtime import PageType
from whochat.ocr.models import OcrRegion, OcrResult, ParsedOcrMessage
from whochat.ocr.parser import normalize_ocr_regions
from whochat.services.pipeline import PipelineResult
from whochat.services.transcript_stitcher import StitchedMessage, TranscriptStitcher
from whochat.storage.repositories import ContactRepository, LogRepository, MessageRepository


@dataclass(frozen=True)
class IngestionResult:
    accepted: bool
    reason: str
    contact: Contact | None
    inserted_messages: int
    duplicate_messages: int
    title_candidates: tuple[str, ...] = field(default_factory=tuple)


class ChatIngestionService:
    def __init__(
        self,
        contacts: ContactRepository,
        messages: MessageRepository,
        logs: LogRepository | None = None,
        transcript_stitcher: TranscriptStitcher | None = None,
        *,
        min_page_confidence: float = 0.65,
        min_title_confidence: float = 0.50,
        min_message_confidence: float = 0.42,
    ) -> None:
        self.contacts = contacts
        self.messages = messages
        self.logs = logs
        self.min_page_confidence = min_page_confidence
        self.min_title_confidence = min_title_confidence
        self.min_message_confidence = min_message_confidence
        self.last_result: IngestionResult | None = None
        self.transcript_stitcher = transcript_stitcher or TranscriptStitcher()

    def ingest_pipeline_result(self, result: PipelineResult) -> IngestionResult:
        if not result.page.can_generate_reply or result.page.confidence < self.min_page_confidence:
            return self._finish(IngestionResult(False, f"page_blocked:{result.page.page_type.value}", None, 0, 0))
        if result.ocr_result.warning:
            return self._finish(IngestionResult(False, f"ocr_warning:{result.ocr_result.warning}", None, 0, 0))
        title_candidates = extract_title_candidates(
            result.ocr_result,
            result,
            min_confidence=self.min_title_confidence,
        )
        raw_title = title_candidates[0] if title_candidates else None
        title = normalize_contact_title(
            raw_title,
            ConversationType.GROUP if result.page.page_type == PageType.CHAT_GROUP else ConversationType.DM,
        ) if raw_title else None
        if title is None:
            debug_lines = tuple(_title_candidate_debug_lines(result.ocr_result, result))
            return self._finish(
                IngestionResult(
                    False,
                    f"contact_title_unavailable:{_format_title_candidates(debug_lines)}",
                    None,
                    0,
                    0,
                    debug_lines,
                )
            )

        contact = self.contacts.create_or_get_by_display_name(
            title,
            platform=_platform_from_result(result),
            conversation_type=ConversationType.GROUP if result.page.page_type == PageType.CHAT_GROUP else ConversationType.DM,
        )
        _add_raw_title_alias(self.contacts, contact, raw_title, title)
        if contact.status == ContactStatus.UNCONFIRMED:
            contact = self.contacts.update_profile(contact.id, status=ContactStatus.SUSPECTED)

        stitch = self.transcript_stitcher.observe(
            contact.id,
            [message for message in result.messages if message.confidence >= self.min_message_confidence],
            observed_at=result.created_at,
        )
        new_messages = _new_stitched_messages(stitch.messages, stitch.inserted_before, stitch.inserted_after)
        inserted = 0
        duplicate = 0
        for stitched in new_messages:
            message = message_from_stitched(contact.id, stitched, result)
            if self.messages.add_message(message):
                inserted += 1
            else:
                duplicate += 1

        visible_duplicates = stitch.duplicate_visible if not new_messages else 0
        duplicate += visible_duplicates
        reason = f"messages_ingested:{stitch.reason}"
        return self._finish(
            IngestionResult(True, reason, contact, inserted, duplicate, tuple(_title_candidate_debug_lines(result.ocr_result, result)))
        )

    def ingest_title_result(self, result) -> IngestionResult:
        if result.ocr_result.warning:
            return self._finish(
                IngestionResult(False, f"title_ocr_warning:{result.ocr_result.warning}", None, 0, 0)
            )
        title_candidates = extract_title_candidates(
            result.ocr_result,
            result,
            min_confidence=self.min_title_confidence,
        )
        raw_title = title_candidates[0] if title_candidates else None
        conversation_type = _conversation_type_from_title(raw_title or "")
        title = normalize_contact_title(raw_title, conversation_type) if raw_title else None
        if title is None:
            debug_lines = tuple(_title_candidate_debug_lines(result.ocr_result, result))
            return self._finish(
                IngestionResult(
                    False,
                    f"title_unavailable:{_format_title_candidates(debug_lines)}",
                    None,
                    0,
                    0,
                    debug_lines,
                )
            )
        contact = self.contacts.create_or_get_by_display_name(
            title,
            platform=_platform_from_result(result),
            conversation_type=conversation_type,
        )
        _add_raw_title_alias(self.contacts, contact, raw_title, title)
        if contact.status == ContactStatus.UNCONFIRMED:
            contact = self.contacts.update_profile(contact.id, status=ContactStatus.SUSPECTED)
        return self._finish(
            IngestionResult(
                True,
                "title_ingested",
                contact,
                0,
                0,
                tuple(_title_candidate_debug_lines(result.ocr_result, result)),
            )
        )

    def _finish(self, result: IngestionResult) -> IngestionResult:
        self.last_result = result
        if self.logs:
            contact_id = result.contact.id if result.contact else "-"
            self.logs.append(
                "info" if result.accepted else "warning",
                "ingestion",
                "pipeline_ingestion",
                (
                    f"accepted={result.accepted}, reason={result.reason}, contact={contact_id}, "
                    f"inserted={result.inserted_messages}, duplicate={result.duplicate_messages}, "
                    f"title_candidates={','.join(result.title_candidates) or '-'}"
                ),
            )
        return result


def extract_contact_title(ocr_result: OcrResult, result: PipelineResult) -> str | None:
    candidates = extract_title_candidates(ocr_result, result)
    return candidates[0] if candidates else None


def extract_title_candidates(
    ocr_result: OcrResult,
    result: PipelineResult,
    *,
    min_confidence: float = 0.50,
) -> list[str]:
    normalized = normalize_ocr_regions(ocr_result, result.layout)
    candidates = [
        box for box in normalized.boxes
        if box.region == OcrRegion.TITLE and box.confidence >= min_confidence and _looks_like_contact_title(box.text)
    ]
    candidates.sort(key=lambda box: (-box.confidence, box.rect.top, box.rect.left))
    return [_normalize_spaces(box.text.strip())[:80] for box in candidates if box.text.strip()]


def normalize_contact_title(title: str | None, conversation_type: ConversationType) -> str | None:
    if title is None:
        return None
    text = _normalize_spaces(title)
    if conversation_type == ConversationType.GROUP:
        text = _strip_group_member_count(text)
    return text[:80] if text else None


def _title_candidate_debug_lines(ocr_result: OcrResult, result: PipelineResult) -> list[str]:
    normalized = normalize_ocr_regions(ocr_result, result.layout)
    boxes = [
        box for box in normalized.boxes
        if box.text.strip() and box.region in {OcrRegion.TITLE, OcrRegion.UNKNOWN}
    ]
    boxes.sort(key=lambda box: (-box.confidence, box.rect.top, box.rect.left))
    return [
        f"{box.region.value}:{box.confidence:.2f}:{_clip_debug_text(box.text)}"
        for box in boxes[:8]
    ]


def _format_title_candidates(lines: tuple[str, ...] | list[str]) -> str:
    return "|".join(lines) if lines else "none"


def _clip_debug_text(value: str, limit: int = 48) -> str:
    text = " ".join(value.strip().split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _platform_from_result(result: PipelineResult) -> str:
    platform = (getattr(result, "target_app", "") or "").strip().lower()
    if platform:
        return platform
    return "wechat"


def _conversation_type_from_title(title: str) -> ConversationType:
    if "群" in title or "讨论组" in title or "交流群" in title:
        return ConversationType.GROUP
    if any(left in title and right in title for left, right in [("（", "）"), ("(", ")")]):
        import re

        if re.search(r"[（(]\s*\d{2,}\s*[)）]", title):
            return ConversationType.GROUP
    return ConversationType.DM


def _strip_group_member_count(title: str) -> str:
    previous = title
    while True:
        text = re.sub(r"\s*[（(]\s*\d{2,}\s*[)）]\s*$", "", previous).strip()
        if text == previous:
            return text
        previous = text


def _normalize_spaces(value: str) -> str:
    return " ".join(value.strip().split())


def _add_raw_title_alias(contacts: ContactRepository, contact: Contact, raw_title: str | None, normalized_title: str | None) -> None:
    if not raw_title or not normalized_title:
        return
    raw = _normalize_spaces(raw_title)
    if raw and raw != normalized_title:
        contacts.add_alias(contact.id, raw, "ocr_title")


def message_from_parsed(contact_id: str, parsed: ParsedOcrMessage, result: PipelineResult) -> Message:
    return Message(
        id=_fingerprint("message-id", contact_id, parsed, result),
        contact_id=contact_id,
        speaker=parsed.speaker,
        text=parsed.text.strip(),
        content_type="text",
        ocr_confidence=parsed.confidence,
        observed_at=result.created_at,
        message_time=_resolved_message_time(parsed, result),
        time_source="ocr" if parsed.time_text else "observed",
        partial=parsed.partial,
        fingerprint=_fingerprint("ocr", contact_id, parsed, result),
        source=f"ocr_pipeline:{result.ocr_result.engine}",
    )


def message_from_stitched(contact_id: str, stitched: StitchedMessage, result: PipelineResult) -> Message:
    return Message(
        id=_stitched_fingerprint("message-id", contact_id, stitched, result),
        contact_id=contact_id,
        speaker=stitched.speaker,
        text=stitched.text.strip(),
        content_type="text",
        ocr_confidence=stitched.confidence,
        observed_at=stitched.first_seen_at,
        message_time=stitched.message_time,
        time_source=stitched.time_source,
        partial=stitched.partial,
        fingerprint=_stitched_fingerprint("stitched", contact_id, stitched, result),
        source=f"ocr_stitched:{result.ocr_result.engine}",
    )


def _fingerprint(prefix: str, contact_id: str, parsed: ParsedOcrMessage, result: PipelineResult) -> str:
    bucket = (
        contact_id,
        parsed.speaker.value,
        parsed.text.strip(),
        str(round(parsed.confidence, 1)),
        str(parsed.partial),
        ",".join(str(value) for value in parsed.rect.as_tuple()),
        result.ocr_result.engine,
    )
    digest = hashlib.sha256("|".join(bucket).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _stitched_fingerprint(prefix: str, contact_id: str, stitched: StitchedMessage, result: PipelineResult) -> str:
    bucket = (
        contact_id,
        stitched.speaker.value,
        " ".join(stitched.text.strip().split()).lower(),
        result.ocr_result.engine,
    )
    digest = hashlib.sha256("|".join(bucket).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _new_stitched_messages(
    messages: list[StitchedMessage],
    inserted_before: int,
    inserted_after: int,
) -> list[StitchedMessage]:
    selected: list[StitchedMessage] = []
    if inserted_before > 0:
        selected.extend(messages[:inserted_before])
    if inserted_after > 0:
        selected.extend(messages[len(messages) - inserted_after:])
    return selected


def _looks_like_contact_title(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    blocked = {"微信", "WeChat", "搜索", "设置", "通讯录", "聊天信息", "文件传输助手", "X", "x", "×", "□", "口", "-", "_", "—"}
    if text in blocked:
        return False
    if len(text) <= 1 and not any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return False
    if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
        return False
    return len(text) <= 80


def _resolved_message_time(parsed: ParsedOcrMessage, result: PipelineResult) -> str | None:
    if not parsed.time_text:
        return None
    observed = result.created_at
    try:
        from whochat.services.transcript_stitcher import _resolve_message_time

        resolved, source = _resolve_message_time(parsed.time_text, observed)
    except Exception:
        return None
    return resolved if source == "ocr" else None
