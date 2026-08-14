from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.core.models import Speaker
from whochat.core.runtime import Rect
from whochat.ocr.models import ParsedOcrMessage
from whochat.services.transcript_stitcher import TranscriptStitcher


def main() -> int:
    stitcher = TranscriptStitcher(min_overlap=2)
    first = stitcher.observe("chat-1", [_msg(Speaker.OTHER, "A"), _msg(Speaker.ME, "B"), _msg(Speaker.OTHER, "C")], observed_at="t1")
    if first.reason != "initialized_from_visible_window" or len(first.messages) != 3:
        raise RuntimeError(first)

    down = stitcher.observe("chat-1", [_msg(Speaker.ME, "B"), _msg(Speaker.OTHER, "C"), _msg(Speaker.ME, "D")], observed_at="t2")
    if down.reason != "appended_after_overlap" or [item.text for item in down.messages] != ["A", "B", "C", "D"]:
        raise RuntimeError(down)

    up = stitcher.observe("chat-1", [_msg(Speaker.ME, "Z"), _msg(Speaker.OTHER, "A"), _msg(Speaker.ME, "B")], observed_at="t3")
    if up.reason != "prepended_before_overlap" or [item.text for item in up.messages] != ["Z", "A", "B", "C", "D"]:
        raise RuntimeError(up)

    repeat = stitcher.observe("chat-1", [_msg(Speaker.OTHER, "A"), _msg(Speaker.ME, "B")], observed_at="t4")
    if repeat.reason != "visible_window_already_known" or repeat.messages[1].observations < 3:
        raise RuntimeError(repeat)

    jump = stitcher.observe("chat-1", [_msg(Speaker.ME, "X"), _msg(Speaker.OTHER, "Y")], observed_at="t5")
    if jump.reason != "no_reliable_overlap_pending_segment" or jump.pending_segment != 2:
        raise RuntimeError(jump)
    if [item.text for item in jump.pending_messages] != ["X", "Y"]:
        raise RuntimeError(f"pending visible segment was not retained: {jump.pending_messages}")

    partial = stitcher.observe("chat-2", [_msg(Speaker.OTHER, "边缘消息", partial=True), _msg(Speaker.ME, "稳定消息")], observed_at="t6")
    if [item.text for item in partial.messages] != ["稳定消息"]:
        raise RuntimeError(partial)

    timestamped = stitcher.observe(
        "chat-3",
        [_msg(Speaker.OTHER, "第一条"), _msg(Speaker.ME, "第二条")],
        observed_at="2026-01-01T08:00:00+00:00",
    )
    if [item.message_time for item in timestamped.messages] != [
        "2026-01-01T08:00:00+00:00",
        "2026-01-01T08:00:00.001000+00:00",
    ]:
        raise RuntimeError(f"OCR fallback timestamps are not ordered: {timestamped.messages}")
    if any(item.time_source != "ocr_observed" for item in timestamped.messages):
        raise RuntimeError(f"OCR fallback timestamp source is missing: {timestamped.messages}")

    print(f"merged={len(up.messages)} pending={jump.pending_segment} partial_filtered={len(partial.messages)} timestamped={len(timestamped.messages)}")
    return 0


def _msg(speaker: Speaker, text: str, partial: bool = False) -> ParsedOcrMessage:
    return ParsedOcrMessage(speaker, text, Rect(0, 0, 100, 30), 0.9, partial, "verify")


if __name__ == "__main__":
    raise SystemExit(main())
