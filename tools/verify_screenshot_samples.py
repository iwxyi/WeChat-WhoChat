from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.config import OcrConfig
from whochat.ocr.engine import create_ocr_engine
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.ocr.parser import classify_page_from_ocr, normalize_ocr_regions, parse_visible_messages
from whochat.core.runtime import Rect
from tools.replay_ocr_sample import load_layout


def main() -> int:
    args = _parse_args()
    root = Path(args.samples).resolve()
    manifests = sorted(root.glob("*/manifest.json"))
    if not manifests:
        raise SystemExit(f"no screenshot sample manifests found under {root}")
    for manifest in manifests:
        _verify_manifest(manifest, args.provider, args.language, args.min_confidence, args.use_gpu)
    print(f"screenshot_samples={len(manifests)} passed")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay screenshot samples with layout and expected parser results.")
    parser.add_argument("--samples", default=str(ROOT / "fixtures" / "screenshot_samples"))
    parser.add_argument("--provider", default="structured", help="structured uses boxes from manifest; otherwise runs OCR provider")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--use-gpu", action="store_true")
    return parser.parse_args()


def _verify_manifest(
    manifest_path: Path,
    provider: str,
    language: str,
    min_confidence: float,
    use_gpu: bool,
) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    image_path = (base / data["image"]).resolve()
    layout_path = (base / data["layout"]).resolve()
    layout = load_layout(image_path, layout_path)
    if provider == "structured":
        result = _structured_result(data, image_path, manifest_path)
    else:
        engine = create_ocr_engine(OcrConfig(provider=provider, language=language, min_confidence=min_confidence, use_gpu=use_gpu))
        result = engine.recognize(image_path, layout)
    normalized = normalize_ocr_regions(result, layout)
    page = classify_page_from_ocr(normalized, layout)
    messages = parse_visible_messages(normalized, layout)
    expected = data["expected"]
    if page.page_type.value != expected["page_type"]:
        raise RuntimeError(f"{manifest_path}: page={page.page_type.value}, expected={expected['page_type']}; reason={page.reason}")
    if page.can_generate_reply != bool(expected["can_generate_reply"]):
        raise RuntimeError(f"{manifest_path}: can_generate_reply mismatch")
    min_page_confidence = float(expected.get("min_page_confidence", 0.0))
    if page.confidence < min_page_confidence:
        raise RuntimeError(f"{manifest_path}: page confidence {page.confidence:.2f} below {min_page_confidence:.2f}")
    expected_messages = expected.get("messages", [])
    if len(messages) != len(expected_messages):
        raise RuntimeError(f"{manifest_path}: messages={len(messages)}, expected={len(expected_messages)}")
    for index, (message, expected_message) in enumerate(zip(messages, expected_messages)):
        for key, value in expected_message.items():
            actual = {
                "speaker": message.speaker.value,
                "text": message.text,
                "partial": message.partial,
                "time_text": message.time_text,
            }.get(key)
            if actual != value:
                raise RuntimeError(f"{manifest_path}: message[{index}].{key}={actual!r}, expected={value!r}")
    print(f"{manifest_path.parent.name}: provider={provider} page={page.page_type.value} messages={len(messages)}")


def _structured_result(data: dict[str, Any], image_path: Path, manifest_path: Path) -> OcrResult:
    boxes = [
        OcrTextBox(
            text=str(item["text"]),
            rect=_rect(item["rect"]),
            confidence=float(item["confidence"]),
            region=OcrRegion.UNKNOWN,
            source=f"sample:{manifest_path.parent.name}",
        )
        for item in data.get("structured_boxes", [])
    ]
    return OcrResult(boxes, str(image_path), "structured-sample")


def _rect(value: Any) -> Rect:
    if not isinstance(value, list | tuple) or len(value) != 4:
        raise ValueError(f"invalid rect: {value!r}")
    return Rect(*(int(item) for item in value))


if __name__ == "__main__":
    raise SystemExit(main())
