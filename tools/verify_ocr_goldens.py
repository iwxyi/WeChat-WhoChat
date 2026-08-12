from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.core.runtime import LayoutRegions, Rect, RegionSource, TargetApp
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.ocr.parser import classify_page_from_ocr, normalize_ocr_regions, parse_visible_messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay structured OCR golden fixtures without initializing a live OCR model.")
    parser.add_argument("--fixtures", default=str(ROOT / "fixtures" / "ocr"), help="Directory containing golden JSON fixtures.")
    args = parser.parse_args()
    fixture_dir = Path(args.fixtures)
    fixtures = sorted(fixture_dir.glob("golden_*.json"))
    if not fixtures:
        raise SystemExit(f"no golden fixtures found in {fixture_dir}")

    for path in fixtures:
        _verify_fixture(path)
    print(f"fixtures={len(fixtures)} passed")
    return 0


def _verify_fixture(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    layout = _layout_from_json(data["layout"])
    result = OcrResult(
        boxes=[
            OcrTextBox(
                text=str(box["text"]),
                rect=_rect(box["rect"]),
                confidence=float(box["confidence"]),
                region=OcrRegion.UNKNOWN,
                source=f"golden:{path.stem}",
            )
            for box in data["boxes"]
        ],
        source_image=f"golden:{path.name}",
        engine="golden",
    )
    normalized = normalize_ocr_regions(result, layout)
    page = classify_page_from_ocr(normalized, layout)
    messages = parse_visible_messages(normalized, layout)
    expected = data["expected"]
    expected_type = expected["page_type"]
    if page.page_type.value != expected_type:
        raise RuntimeError(f"{path.name}: page type {page.page_type.value!r}, expected {expected_type!r}; reason={page.reason}")
    if page.confidence < float(expected.get("min_page_confidence", 0.0)):
        raise RuntimeError(f"{path.name}: page confidence {page.confidence:.2f} below expected minimum")
    if page.can_generate_reply != bool(expected["can_generate_reply"]):
        raise RuntimeError(f"{path.name}: can_generate_reply mismatch")
    expected_messages = expected["messages"]
    if len(messages) != len(expected_messages):
        raise RuntimeError(f"{path.name}: messages {len(messages)}, expected {len(expected_messages)}")
    for index, (message, golden) in enumerate(zip(messages, expected_messages)):
        fields = {
            "speaker": message.speaker.value,
            "text": message.text,
            "partial": message.partial,
            "time_text": message.time_text,
        }
        for key, expected_value in golden.items():
            if fields.get(key) != expected_value:
                raise RuntimeError(
                    f"{path.name}: message[{index}] {key}={fields.get(key)!r}, expected {expected_value!r}"
                )
    print(f"{path.name}: page={page.page_type.value} messages={len(messages)} confidence={page.confidence:.2f}")


def _layout_from_json(data: dict[str, Any]) -> LayoutRegions:
    return LayoutRegions(
        target_app=TargetApp.WECHAT,
        bubble_profile="wechat_green",
        window_rect=_rect(data["window_rect"]),
        nav_rect=_rect(data["nav_rect"]),
        chat_list_rect=_rect(data["chat_list_rect"]),
        content_rect=_rect(data["content_rect"]),
        title_rect=_rect(data["title_rect"]),
        message_rect=_rect(data["message_rect"]),
        input_rect=_rect(data["input_rect"]),
        confidence=float(data.get("confidence", 0.9)),
        source=RegionSource(str(data.get("source", "calibrated"))),
        reason=str(data.get("reason", "golden fixture")),
    )


def _rect(value: Any) -> Rect:
    if not isinstance(value, list | tuple) or len(value) != 4:
        raise ValueError(f"invalid rect: {value!r}")
    return Rect(*(int(item) for item in value))


if __name__ == "__main__":
    raise SystemExit(main())
