from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from whochat.config import OcrConfig
from whochat.diagnostics import configure_native_runtime_limits
from whochat.ocr.engine import (
    _boxes_from_paddle_result,
    _configure_paddle_cache,
    _run_paddle_ocr,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--use-gpu", choices=["0", "1"], default="0")
    args = parser.parse_args()

    image_path = Path(args.image_path)
    config = OcrConfig(
        provider="PaddleOCR",
        language=args.language,
        min_confidence=args.min_confidence,
        use_gpu=args.use_gpu == "1",
    )
    with contextlib.redirect_stdout(sys.stderr):
        boxes = _recognize(image_path, config)
    payload = {
        "boxes": [
            {
                "text": box.text,
                "rect": list(box.rect.as_tuple()),
                "confidence": box.confidence,
            }
            for box in boxes
        ],
        "warning": None if boxes else "PaddleOCR 未返回文本",
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def _recognize(image_path: Path, config: OcrConfig):
    if not image_path.exists():
        raise FileNotFoundError(str(image_path))
    configure_native_runtime_limits()
    _configure_paddle_cache()
    from paddleocr import PaddleOCR

    attempts = [
        {
            "device": "gpu" if config.use_gpu else "cpu",
            "enable_mkldnn": False,
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_recognition_model_name": "PP-OCRv5_mobile_rec",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "cpu_threads": 1,
        },
        {"lang": config.language, "use_angle_cls": False},
        {"lang": config.language},
    ]
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            engine = PaddleOCR(**kwargs)
            raw = _run_paddle_ocr(engine, image_path)
            return _boxes_from_paddle_result(raw, config.min_confidence, "paddleocr")
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


if __name__ == "__main__":
    raise SystemExit(main())
