from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from whochat.core.runtime import Rect
from whochat.core.models import Speaker


class OcrRegion(StrEnum):
    TITLE = "title"
    CHAT_LIST = "chat_list"
    MESSAGE = "message"
    INPUT = "input"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OcrTextBox:
    text: str
    rect: Rect
    confidence: float
    region: OcrRegion
    source: str


@dataclass(frozen=True)
class OcrResult:
    boxes: list[OcrTextBox]
    source_image: str
    engine: str
    warning: str | None = None

    def summary_lines(self, limit: int = 12) -> list[str]:
        lines = [
            f"engine={self.engine}",
            f"boxes={len(self.boxes)}",
        ]
        if self.warning:
            lines.append(f"warning={self.warning}")
        for box in self.boxes[:limit]:
            lines.append(f"[{box.region.value}] {box.confidence:.2f} {box.text} {box.rect.as_tuple()}")
        return lines


@dataclass(frozen=True)
class ParsedOcrMessage:
    speaker: Speaker
    text: str
    rect: Rect
    confidence: float
    partial: bool
    reason: str
    time_text: str | None = None
