from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "autocapture_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.platform.window_tracker import WindowInfo
from whochat.services.autocapture import AutoCaptureController
from whochat.services.bootstrap import build_services


class FakePipeline:
    def __init__(self) -> None:
        self.submitted = []
        self.is_running = False

    def submit(self, state):
        self.submitted.append(state)
        return len(self.submitted)


def main() -> int:
    QCoreApplication.instance() or QCoreApplication(sys.argv)
    services = build_services()
    services.runtime.capture_gate.policy = replace(services.runtime.capture_gate.policy, scroll_debounce_ms=0)
    pipeline = FakePipeline()
    controller = AutoCaptureController(services.runtime, pipeline)
    window = WindowInfo(hwnd=7001, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)

    controller.on_window_changed(window)
    controller.on_window_changed(window)
    if not controller.pending:
        raise RuntimeError("transient throttling should not cancel pending capture")
    job = controller.flush_pending()
    if job != 1 or len(pipeline.submitted) != 1:
        raise RuntimeError(f"expected one auto capture submission, got job={job} count={len(pipeline.submitted)}")

    services.runtime.set_paused(True)
    controller.on_window_changed(window)
    if controller.pending:
        raise RuntimeError("paused capture should not remain pending")
    if controller.flush_pending() is not None:
        raise RuntimeError("paused capture should not submit")

    services.runtime.set_paused(False)
    controller.set_enabled(False)
    controller.on_window_changed(window)
    if controller.pending or controller.flush_pending() is not None:
        raise RuntimeError("disabled auto capture should not submit")

    print(f"submitted={len(pipeline.submitted)} last_job={controller.last_submit_job_id} pending={controller.pending}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
