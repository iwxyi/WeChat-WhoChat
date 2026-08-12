from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "paddleocr_real_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from PIL import Image, ImageDraw, ImageFont

from whochat.config import OcrConfig
from whochat.core.runtime import LayoutRegions, Rect, RegionSource, TargetApp
from whochat.ocr.engine import PaddleOcrEngine
from whochat.ocr.parser import normalize_ocr_regions, parse_visible_messages


def main() -> int:
    image_path = DATA_DIR / "wechat_text.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    _write_sample(image_path)
    layout = LayoutRegions(
        target_app=TargetApp.WECHAT,
        bubble_profile="wechat_green",
        window_rect=Rect(0, 0, 900, 620),
        nav_rect=Rect(0, 0, 70, 620),
        chat_list_rect=Rect(70, 0, 285, 620),
        content_rect=Rect(285, 0, 900, 620),
        title_rect=Rect(285, 0, 900, 70),
        message_rect=Rect(285, 70, 900, 480),
        input_rect=Rect(285, 480, 900, 620),
        confidence=0.9,
        source=RegionSource.AUTO,
        reason="synthetic paddleocr verification",
    )
    result = PaddleOcrEngine(OcrConfig(provider="PaddleOCR", min_confidence=0.1)).recognize(image_path, layout)
    normalized = normalize_ocr_regions(result, layout)
    messages = parse_visible_messages(normalized, layout)
    if result.warning:
        raise RuntimeError(result.warning)
    text = "\n".join(box.text for box in normalized.boxes)
    if "WhoChat" not in text and "hello" not in text.lower():
        raise RuntimeError(f"PaddleOCR did not recognize expected sample text: {text!r}")
    if not messages:
        raise RuntimeError("PaddleOCR recognized text but parser produced no visible messages")
    print(f"boxes={len(normalized.boxes)} messages={len(messages)} text={text!r}")
    return 0


def _write_sample(image_path: Path) -> None:
    image = Image.new("RGB", (900, 620), "#f5f5f5")
    draw = ImageDraw.Draw(image)
    font = _font(30)
    small = _font(24)
    draw.rectangle((285, 0, 900, 70), fill="#ffffff")
    draw.text((320, 20), "WhoChat Test", fill="#111111", font=font)
    draw.rounded_rectangle((330, 120, 610, 172), radius=8, fill="#ffffff")
    draw.text((350, 132), "hello boss", fill="#111111", font=small)
    draw.rounded_rectangle((585, 230, 840, 282), radius=8, fill="#95ec69")
    draw.text((610, 242), "WhoChat ok", fill="#111111", font=small)
    draw.rectangle((285, 480, 900, 620), fill="#ffffff")
    draw.text((330, 520), "input area", fill="#777777", font=small)
    image.save(image_path)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


if __name__ == "__main__":
    raise SystemExit(main())
