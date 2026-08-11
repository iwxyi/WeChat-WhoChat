from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "capture_performance_summary_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    window = MainWindow(services)
    empty = "\n".join(window._format_capture_performance_summary())
    if "capture_perf=暂无" not in empty:
        raise RuntimeError(f"empty capture performance summary mismatch: {empty}")

    _append_sample(services, 1, title_ms=1000, content_ms=6000, total_ms=8000)
    ok = "\n".join(window._format_capture_performance_summary())
    if "status:ok" not in ok or "avg_total_ms:8000" not in ok:
        raise RuntimeError(f"ok capture performance summary mismatch: {ok}")

    _append_sample(services, 2, title_ms=7000, content_ms=45000, total_ms=52000)
    slow = "\n".join(window._format_capture_performance_summary())
    if "status:warning" not in slow or "slowest_job:2" not in slow:
        raise RuntimeError(f"warning capture performance summary mismatch: {slow}")

    _append_sample(services, 3, title_ms=12000, content_ms=130000, total_ms=145000)
    very_slow = "\n".join(window._format_capture_performance_summary())
    if "status:slow" not in very_slow or "PaddleOCR worker" not in very_slow:
        raise RuntimeError(f"slow capture performance summary mismatch: {very_slow}")

    print(very_slow)
    window.close()
    app.quit()
    return 0


def _append_sample(services, job_id: int, *, title_ms: int, content_ms: int, total_ms: int) -> None:
    services.capture_samples.append(
        job_id=job_id,
        hwnd=job_id,
        target_app="wechat",
        app_label="微信",
        snapshot_hash=f"hash-{job_id}",
        image_path=f"capture-{job_id}.png",
        ocr_image_path=f"capture-{job_id}_content.png",
        crop_rect_json="[0,0,100,100]",
        title_ocr_image_path=f"capture-{job_id}_title.png",
        title_crop_rect_json="[0,0,100,20]",
        title_ocr_elapsed_ms=title_ms,
        content_ocr_elapsed_ms=content_ms,
        total_elapsed_ms=total_ms,
        ocr_engine="verify",
        ocr_warning="",
        page_type="chat_dm",
        page_confidence=0.9,
        message_count=2,
        retained_image=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
