from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "autocapture_performance_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["WHOCHAT_HEAVY_OCR_MIN_INTERVAL_MS"] = "8000"
os.environ["WHOCHAT_SLOW_OCR_MIN_INTERVAL_MS"] = "60000"

from whochat.platform.window_tracker import WindowInfo
from whochat.services.autocapture import AutoCaptureController
from whochat.services.bootstrap import build_services


class FakeOcrEngine:
    name = "paddleocr"


class FakePipeline:
    def __init__(self, capture_samples) -> None:
        self.submitted = []
        self.is_running = False
        self.ocr_engine = FakeOcrEngine()
        self.capture_samples = capture_samples

    def submit(self, state):
        self.submitted.append(state)
        return len(self.submitted)


def main() -> int:
    QCoreApplication.instance() or QCoreApplication(sys.argv)
    services = build_services()
    services.runtime.capture_gate.policy = replace(
        services.runtime.capture_gate.policy,
        scroll_debounce_ms=0,
        ocr_min_interval_ms=2500,
    )
    pipeline = FakePipeline(services.capture_samples)
    controller = AutoCaptureController(services.runtime, pipeline)
    window = WindowInfo(hwnd=7001, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)

    controller.on_window_changed(window)
    if controller.flush_pending() != 1:
        raise RuntimeError("initial auto capture should submit")

    _append_perf_sample(services, 20000, job_id=1)
    _append_perf_sample(services, 22000, job_id=2)
    controller._last_submit_ms = int(time.monotonic() * 1000) - 30000
    services.runtime.capture_gate.last_capture_ms = 0
    controller.on_window_changed(window)
    if controller.flush_pending() is not None:
        raise RuntimeError("warning OCR performance should extend auto capture interval")

    controller._last_submit_ms = int(time.monotonic() * 1000) - 45000
    services.runtime.capture_gate.last_capture_ms = 0
    controller.on_window_changed(window)
    if controller.flush_pending() != 2:
        raise RuntimeError("warning OCR performance should allow capture after extended interval")

    _append_perf_sample(services, 70000, job_id=3)
    _append_perf_sample(services, 80000, job_id=4)
    controller._last_submit_ms = int(time.monotonic() * 1000) - 90000
    services.runtime.capture_gate.last_capture_ms = 0
    controller.on_window_changed(window)
    if controller.flush_pending() is not None:
        raise RuntimeError("slow OCR performance should heavily rate-limit auto capture")

    print(f"submitted={len(pipeline.submitted)} last_job={controller.last_submit_job_id}")
    return 0


def _append_perf_sample(services, total_ms: int, *, job_id: int) -> None:
    services.capture_samples.append(
        job_id=job_id,
        hwnd=7001,
        target_app="wechat",
        app_label="微信",
        snapshot_hash=f"hash-{job_id}",
        image_path="",
        ocr_image_path="",
        crop_rect_json="",
        title_ocr_image_path="",
        title_crop_rect_json="",
        title_ocr_elapsed_ms=800,
        content_ocr_elapsed_ms=max(1, total_ms - 1000),
        total_elapsed_ms=total_ms,
        ocr_engine="paddleocr",
        ocr_warning="",
        page_type="direct_chat",
        page_confidence=0.9,
        message_count=2,
        retained_image=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
