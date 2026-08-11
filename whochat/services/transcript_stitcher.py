from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from whochat.core.models import Speaker, utc_now_iso
from whochat.ocr.models import ParsedOcrMessage


@dataclass(frozen=True)
class StitchedMessage:
    speaker: Speaker
    text: str
    confidence: float
    partial: bool
    first_seen_at: str
    last_seen_at: str
    message_time: str | None = None
    time_source: str = "observed"
    observations: int = 1
    sender_name: str = ""


@dataclass(frozen=True)
class StitchResult:
    messages: list[StitchedMessage]
    inserted_before: int
    inserted_after: int
    duplicate_visible: int
    pending_segment: int
    reason: str


class TranscriptStitcher:
    def __init__(self, *, min_overlap: int = 2) -> None:
        self.min_overlap = min_overlap
        self._transcripts: dict[str, list[StitchedMessage]] = {}

    def get_messages(self, conversation_id: str) -> list[StitchedMessage]:
        return list(self._transcripts.get(conversation_id, []))

    def reset(self, conversation_id: str) -> None:
        self._transcripts.pop(conversation_id, None)

    def observe(
        self,
        conversation_id: str,
        visible_messages: list[ParsedOcrMessage],
        *,
        observed_at: str | None = None,
    ) -> StitchResult:
        observed_at = observed_at or utc_now_iso()
        visible = [
            _from_parsed(message, observed_at)
            for message in visible_messages
            if _usable(message)
        ]
        current = self._transcripts.get(conversation_id, [])
        if not visible:
            return StitchResult(current, 0, 0, 0, 0, "no_usable_visible_messages")
        if not current:
            self._transcripts[conversation_id] = visible
            return StitchResult(visible, 0, len(visible), 0, 0, "initialized_from_visible_window")

        contained = _contained_at(current, visible)
        if contained is not None:
            merged = _refresh_observations(current, visible, contained, observed_at)
            self._transcripts[conversation_id] = merged
            return StitchResult(merged, 0, 0, len(visible), 0, "visible_window_already_known")

        append_overlap = _suffix_prefix_overlap(current, visible)
        prepend_overlap = _suffix_prefix_overlap(visible, current)
        if append_overlap >= self.min_overlap and append_overlap >= prepend_overlap:
            tail = visible[append_overlap:]
            merged = _refresh_observations(current, visible[:append_overlap], len(current) - append_overlap, observed_at) + tail
            self._transcripts[conversation_id] = merged
            return StitchResult(merged, 0, len(tail), append_overlap, 0, "appended_after_overlap")
        if prepend_overlap >= self.min_overlap:
            head = visible[: len(visible) - prepend_overlap]
            refreshed = _refresh_observations(current, visible[len(head):], 0, observed_at)
            merged = head + refreshed
            self._transcripts[conversation_id] = merged
            return StitchResult(merged, len(head), 0, prepend_overlap, 0, "prepended_before_overlap")

        return StitchResult(current, 0, 0, 0, len(visible), "no_reliable_overlap_pending_segment")


def _usable(message: ParsedOcrMessage) -> bool:
    if message.partial:
        return False
    if message.speaker in {Speaker.SYSTEM, Speaker.UNKNOWN}:
        return False
    return bool(_normalize_text(message.text))


def _from_parsed(message: ParsedOcrMessage, observed_at: str) -> StitchedMessage:
    resolved_time, time_source = _resolve_message_time(message.time_text, observed_at)
    return StitchedMessage(
        speaker=message.speaker,
        text=message.text.strip(),
        confidence=message.confidence,
        partial=message.partial,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        message_time=resolved_time,
        time_source=time_source,
        sender_name=message.sender_name or "",
    )


def _key(message: StitchedMessage) -> tuple[str, str, str]:
    return (message.speaker.value, _normalize_text(message.sender_name), _normalize_text(message.text))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _resolve_message_time(time_text: str | None, observed_at: str) -> tuple[str | None, str]:
    if not time_text:
        return None, "observed"
    observed = _parse_ts(observed_at)
    if observed is None:
        return None, "observed"
    text = time_text.strip()
    match = re.match(r"^(?:(昨天|今天)\s*)?(?:(上午|下午|晚上|中午|凌晨)\s*)?(\d{1,2}):(\d{2})$", text)
    if match:
        day_word, part, hour_text, minute_text = match.groups()
        base = observed
        if day_word == "昨天":
            base = base - timedelta(days=1)
        hour = int(hour_text)
        minute = int(minute_text)
        hour = _apply_day_part(hour, part)
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat(), "ocr"
    match = re.match(
        r"^(\d{1,4})[/-](\d{1,2})[/-](\d{1,2})\s*(?:(上午|下午|晚上|中午|凌晨)\s*)?(\d{1,2}):(\d{2})$",
        text,
    )
    if match:
        year, month, day, part, hour_text, minute_text = match.groups()
        year_i = int(year)
        if year_i < 100:
            year_i += 2000
        hour = _apply_day_part(int(hour_text), part)
        minute = int(minute_text)
        try:
            resolved = observed.replace(
                year=year_i,
                month=int(month),
                day=int(day),
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            return None, "observed"
        return resolved.isoformat(), "ocr"
    return None, "observed"


def _apply_day_part(hour: int, part: str | None) -> int:
    if part in {"下午", "晚上"} and hour < 12:
        return hour + 12
    if part == "中午" and hour < 11:
        return hour + 12
    if part == "凌晨" and hour == 12:
        return 0
    return hour


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(parsed.tzinfo)


def _contained_at(current: list[StitchedMessage], visible: list[StitchedMessage]) -> int | None:
    visible_keys = [_key(item) for item in visible]
    current_keys = [_key(item) for item in current]
    if len(visible_keys) > len(current_keys):
        return None
    for index in range(0, len(current_keys) - len(visible_keys) + 1):
        if current_keys[index:index + len(visible_keys)] == visible_keys:
            return index
    return None


def _suffix_prefix_overlap(left: list[StitchedMessage], right: list[StitchedMessage]) -> int:
    max_size = min(len(left), len(right))
    left_keys = [_key(item) for item in left]
    right_keys = [_key(item) for item in right]
    for size in range(max_size, 0, -1):
        if left_keys[-size:] == right_keys[:size]:
            return size
    return 0


def _refresh_observations(
    current: list[StitchedMessage],
    visible_overlap: list[StitchedMessage],
    start: int,
    observed_at: str,
) -> list[StitchedMessage]:
    merged = list(current)
    for offset, visible in enumerate(visible_overlap):
        index = start + offset
        if index < 0 or index >= len(merged):
            continue
        existing = merged[index]
        merged[index] = replace(
            existing,
            confidence=max(existing.confidence, visible.confidence),
            last_seen_at=observed_at,
            observations=existing.observations + 1,
        )
    return merged
