from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from whochat.config import OcrConfig
from whochat.ocr.engine import _boxes_from_paddle_result, _configure_paddle_cache, _run_paddle_ocr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", default="ch")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--use-gpu", choices=["0", "1"], default="0")
    args = parser.parse_args()

    config = OcrConfig(
        provider="PaddleOCR",
        language=args.language,
        min_confidence=args.min_confidence,
        use_gpu=args.use_gpu == "1",
    )
    with contextlib.redirect_stdout(sys.stderr):
        engine = _create_engine(config)
    _write({"status": "ready"})

    for line in sys.stdin:
        try:
            request = json.loads(line)
            image_path = Path(str(request["image_path"]))
            with contextlib.redirect_stdout(sys.stderr):
                raw = _run_paddle_ocr(engine, image_path)
            boxes = _boxes_from_paddle_result(raw, config.min_confidence, "paddleocr")
            _write(
                {
                    "status": "ok",
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
            )
        except Exception as exc:
            _write({"status": "error", "error": str(exc)})
    return 0


def _create_engine(config: OcrConfig):
    _configure_paddle_cache()
    from paddleocr import PaddleOCR

    return PaddleOCR(
        device="gpu" if config.use_gpu else "cpu",
        enable_mkldnn=False,
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        cpu_threads=1,
    )


def _write(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
