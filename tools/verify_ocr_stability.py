from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["WHOCHAT_DATA_DIR"] = str(ROOT / "tmp" / "ocr_stability_verify")
os.environ["WHOCHAT_DB_PATH"] = str(ROOT / "tmp" / "ocr_stability_verify" / "whochat.db")
os.environ["WHOCHAT_PADDLEOCR_FAILURE_COOLDOWN_SECONDS"] = "2"

from whochat.config import OcrConfig
from whochat.core.runtime import LayoutRegions, Rect, RegionSource
from whochat.ocr.engine import PaddleOcrEngine
from whochat.ocr.models import OcrResult


class FailingPaddle(PaddleOcrEngine):
    def _recognize_in_subprocess(self, image_path: Path) -> OcrResult:
        return OcrResult([], str(image_path), self.name, "PaddleOCR 子进程失败：verify")


def main() -> int:
    image_path = ROOT / "tmp" / "ocr_stability_verify" / "capture.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"not-a-real-png")
    engine = FailingPaddle(OcrConfig(provider="PaddleOCR"))
    layout = _layout()

    first = engine.recognize(image_path, layout)
    second = engine.recognize(image_path, layout)
    third = engine.recognize(image_path, layout)
    if "失败" not in (first.warning or "") or "失败" not in (second.warning or ""):
        raise RuntimeError(f"expected initial failures, got {first.warning!r}, {second.warning!r}")
    if "熔断" not in (third.warning or ""):
        raise RuntimeError(f"expected circuit breaker warning, got {third.warning!r}")
    time.sleep(2.1)
    after = engine.recognize(image_path, layout)
    if "失败" not in (after.warning or ""):
        raise RuntimeError(f"expected retry after cooldown, got {after.warning!r}")
    print(f"warnings={[first.warning, second.warning, third.warning, after.warning]}")
    return 0


def _layout() -> LayoutRegions:
    return LayoutRegions(
        window_rect=Rect(0, 0, 1000, 800),
        nav_rect=Rect(0, 0, 70, 800),
        chat_list_rect=Rect(70, 0, 320, 800),
        content_rect=Rect(320, 0, 1000, 800),
        title_rect=Rect(320, 0, 1000, 80),
        message_rect=Rect(320, 80, 1000, 650),
        input_rect=Rect(320, 650, 1000, 800),
        confidence=0.9,
        source=RegionSource.AUTO,
        reason="verify",
    )


if __name__ == "__main__":
    raise SystemExit(main())
