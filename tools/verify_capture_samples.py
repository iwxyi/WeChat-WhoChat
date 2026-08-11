from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "capture_samples_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.platform.window_tracker import WindowInfo
from whochat.ocr.engine import PreviewOcrEngine
from whochat.services.bootstrap import build_services


def main() -> int:
    services = build_services()
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=801, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    if state.layout is None:
        raise RuntimeError("expected layout")
    services.pipeline.ocr_engine = PreviewOcrEngine()
    services.pipeline.capture_func = _capture
    result = services.pipeline.run_sync(state)
    if result is None or len(result.messages) < 2:
        raise RuntimeError(f"pipeline should produce messages: {result}")
    samples = []
    for _ in range(20):
        samples = services.capture_samples.tail(5)
        if samples:
            break
        time.sleep(0.05)
    if len(samples) != 1:
        raise RuntimeError(f"expected one capture sample, got {len(samples)}")
    sample = samples[0]
    if sample.snapshot_hash != result.snapshot_hash or sample.message_count != len(result.messages):
        raise RuntimeError(f"capture sample mismatch: {sample}")
    if sample.target_app != "wechat" or sample.app_label != "微信":
        raise RuntimeError(f"capture sample should retain target app context: {sample.target_app}/{sample.app_label}")
    if not sample.title_ocr_image_path or not sample.title_crop_rect_json:
        raise RuntimeError(f"capture sample should retain title OCR crop metadata: {sample}")
    if sample.title_ocr_elapsed_ms is None or sample.content_ocr_elapsed_ms is None or sample.total_elapsed_ms is None:
        raise RuntimeError(f"capture sample should retain OCR timings: {sample}")
    serialized = repr(sample)
    if "下午前能确认吗" in serialized or "我看一下后回复你" in serialized:
        raise RuntimeError("capture sample metadata must not contain chat text")
    print(f"samples={len(samples)} page={sample.page_type} messages={sample.message_count} retained={sample.retained_image}")
    return 0


def _capture(_rect, output: Path) -> Path:
    image = Image.new("RGB", (1200, 800), "#f6f7f9")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 72, 800), fill="#1f2933")
    draw.rectangle((72, 0, 390, 800), fill="#ffffff")
    draw.rectangle((390, 0, 1200, 64), fill="#ffffff")
    draw.rectangle((390, 64, 1200, 650), fill="#edf2f7")
    draw.rectangle((390, 650, 1200, 800), fill="#ffffff")
    draw.rounded_rectangle((458, 140, 760, 190), radius=8, fill="#ffffff", outline="#d9e2ec")
    draw.rounded_rectangle((800, 230, 1130, 282), radius=8, fill="#d7f5e8", outline="#b7e4d1")
    draw.text((420, 23), "联系人 A", fill="#102a43")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


if __name__ == "__main__":
    raise SystemExit(main())
