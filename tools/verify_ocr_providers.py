from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "ocr_provider_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from PIL import Image

from whochat.config import AppConfig, ConfigStore
from whochat.core.runtime import LayoutRegions, Rect, RegionSource
from whochat.ocr.engine import PaddleOcrEngine, PreviewOcrEngine, RapidOcrEngine, create_ocr_engine


def main() -> int:
    image_path = DATA_DIR / "ocr.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 220), "white").save(image_path)
    layout = LayoutRegions(
        window_rect=Rect(0, 0, 320, 220),
        nav_rect=Rect(0, 0, 40, 220),
        chat_list_rect=Rect(40, 0, 120, 220),
        content_rect=Rect(120, 0, 320, 220),
        title_rect=Rect(120, 0, 320, 32),
        message_rect=Rect(120, 32, 320, 170),
        input_rect=Rect(120, 170, 320, 220),
        confidence=0.9,
        source=RegionSource.AUTO,
        reason="verify",
    )

    config = AppConfig()
    default = create_ocr_engine(config.ocr)
    if not isinstance(default, PaddleOcrEngine):
        raise RuntimeError(f"default OCR provider should be PaddleOCR, got {default}")

    config.ocr.provider = "Preview Fixture"
    preview = create_ocr_engine(config.ocr)
    if not isinstance(preview, PreviewOcrEngine):
        raise RuntimeError(f"preview OCR provider returned {preview}")
    if not preview.recognize(image_path, layout).boxes:
        raise RuntimeError("preview OCR should return fixture boxes")

    config.ocr.provider = "RapidOCR"
    rapid = create_ocr_engine(config.ocr)
    if not isinstance(rapid, RapidOcrEngine):
        raise RuntimeError(f"RapidOCR factory returned {rapid}")
    rapid_result = rapid.recognize(image_path, layout)
    if rapid_result.engine != "rapidocr":
        raise RuntimeError("RapidOCR result should expose engine name")

    config.ocr.provider = "PaddleOCR"
    paddle = create_ocr_engine(config.ocr)
    if not isinstance(paddle, PaddleOcrEngine):
        raise RuntimeError(f"PaddleOCR factory returned {paddle}")
    paddle_result = paddle.recognize(image_path, layout)
    if paddle_result.engine != "paddleocr":
        raise RuntimeError("PaddleOCR result should expose engine name")

    config.ocr.provider = "RapidOCR"
    config.ocr.language = "ch"
    config.ocr.min_confidence = 0.72
    ConfigStore().save(config)
    loaded = ConfigStore().load()
    if loaded.ocr.provider != "RapidOCR" or loaded.ocr.min_confidence != 0.72:
        raise RuntimeError(f"OCR config was not persisted: {loaded.ocr}")

    warnings = [item.warning for item in [rapid_result, paddle_result] if item.warning]
    print(f"preview={preview.name} rapid_warning={bool(rapid_result.warning)} paddle_warning={bool(paddle_result.warning)} warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
