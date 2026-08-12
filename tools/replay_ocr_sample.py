from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.config import OcrConfig
from whochat.core.runtime import LayoutRegions, Rect, RegionSource, TargetApp
from whochat.ocr.engine import create_ocr_engine
from whochat.ocr.parser import classify_page_from_ocr, normalize_ocr_regions, parse_visible_messages


def main() -> int:
    args = _parse_args()
    image_path = Path(args.image).resolve()
    if not image_path.exists():
        raise SystemExit(f"image does not exist: {image_path}")

    layout = load_layout(image_path, Path(args.layout).resolve() if args.layout else None)
    config = OcrConfig(
        provider=args.provider,
        language=args.language,
        min_confidence=args.min_confidence,
        use_gpu=args.use_gpu,
    )
    engine = create_ocr_engine(config)
    raw_result = engine.recognize(image_path, layout)
    result = normalize_ocr_regions(raw_result, layout)
    page = classify_page_from_ocr(result, layout)
    messages = parse_visible_messages(result, layout)

    payload = {
        "image": str(image_path),
        "engine": result.engine,
        "warning": result.warning,
        "layout": _layout_to_json(layout),
        "page": {
            "type": page.page_type.value,
            "confidence": page.confidence,
            "can_generate_reply": page.can_generate_reply,
            "reason": page.reason,
        },
        "boxes": [_box_to_json(box) for box in result.boxes],
        "messages": [_message_to_json(message) for message in messages],
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay OCR on a screenshot sample and print structured parsing output.")
    parser.add_argument("image", help="Screenshot image path.")
    parser.add_argument("--layout", help="Optional layout JSON path. If omitted, a default WeChat-like layout is used.")
    parser.add_argument("--provider", default=os.environ.get("WHOCHAT_OCR_PROVIDER", "PaddleOCR"))
    parser.add_argument("--language", default=os.environ.get("WHOCHAT_OCR_LANGUAGE", "ch"))
    parser.add_argument("--min-confidence", type=float, default=float(os.environ.get("WHOCHAT_OCR_MIN_CONFIDENCE", "0.5")))
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--output", help="Optional output JSON path.")
    return parser.parse_args()


def load_layout(image_path: Path, layout_path: Path | None) -> LayoutRegions:
    with Image.open(image_path) as image:
        width, height = image.size
    window = Rect(0, 0, width, height)
    if layout_path is None:
        return _default_layout(window)
    data = json.loads(layout_path.read_text(encoding="utf-8"))
    return LayoutRegions(
        target_app=TargetApp(str(data.get("target_app", TargetApp.WECHAT.value))),
        bubble_profile=str(data.get("bubble_profile", "wechat_green")),
        window_rect=_rect_from_json(data.get("window_rect"), window),
        nav_rect=_rect_from_json(data["nav_rect"], window),
        chat_list_rect=_rect_from_json(data["chat_list_rect"], window),
        content_rect=_rect_from_json(data["content_rect"], window),
        title_rect=_rect_from_json(data["title_rect"], window),
        message_rect=_rect_from_json(data["message_rect"], window),
        input_rect=_rect_from_json(data["input_rect"], window),
        confidence=float(data.get("confidence", 0.9)),
        source=RegionSource(data.get("source", RegionSource.CALIBRATED.value)),
        reason=str(data.get("reason", f"loaded from {layout_path}")),
    )


def _default_layout(window: Rect) -> LayoutRegions:
    nav_right = round(window.width * 0.075)
    list_right = round(window.width * 0.32)
    title_bottom = round(window.height * 0.105)
    input_top = round(window.height * 0.74)
    return LayoutRegions(
        target_app=TargetApp.WECHAT,
        bubble_profile="wechat_green",
        window_rect=window,
        nav_rect=Rect(0, 0, nav_right, window.height),
        chat_list_rect=Rect(nav_right, 0, list_right, window.height),
        content_rect=Rect(list_right, 0, window.width, window.height),
        title_rect=Rect(list_right, 0, window.width, title_bottom),
        message_rect=Rect(list_right, title_bottom, window.width, input_top),
        input_rect=Rect(list_right, input_top, window.width, window.height),
        confidence=0.55,
        source=RegionSource.AUTO,
        reason="default replay layout; calibrate for reliable WeChat samples",
    )


def _rect_from_json(value: Any, fallback: Rect) -> Rect:
    if value is None:
        return fallback
    if isinstance(value, dict):
        if all(key in value for key in ("left", "top", "right", "bottom")):
            return Rect(int(value["left"]), int(value["top"]), int(value["right"]), int(value["bottom"]))
        if all(key in value for key in ("x", "y", "width", "height")):
            left = int(value["x"])
            top = int(value["y"])
            return Rect(left, top, left + int(value["width"]), top + int(value["height"]))
    if isinstance(value, list | tuple) and len(value) == 4:
        return Rect(int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    raise ValueError(f"invalid rect: {value!r}")


def _layout_to_json(layout: LayoutRegions) -> dict[str, Any]:
    data = asdict(layout)
    data["source"] = layout.source.value
    return data


def _box_to_json(box: Any) -> dict[str, Any]:
    return {
        "text": box.text,
        "rect": box.rect.as_tuple(),
        "confidence": box.confidence,
        "region": box.region.value,
        "source": box.source,
    }


def _message_to_json(message: Any) -> dict[str, Any]:
    return {
        "speaker": message.speaker.value,
        "text": message.text,
        "rect": message.rect.as_tuple(),
        "confidence": message.confidence,
        "partial": message.partial,
        "reason": message.reason,
    }


if __name__ == "__main__":
    raise SystemExit(main())
