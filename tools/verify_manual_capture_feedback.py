from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "manual_capture_feedback_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    window = MainWindow(services)
    window._select_page("diagnostics")

    window._run_capture_pipeline()
    missing_status = window.statusBar().currentMessage()
    if "采集未启动" not in missing_status or "missing" not in missing_status:
        raise RuntimeError(f"missing-window capture feedback is not actionable: {missing_status}")
    if "capture_pipeline_submit_skipped" not in window._log_text.toPlainText():
        raise RuntimeError("manual capture skip should be logged")

    services.runtime.update_from_window_info(
        WindowInfo(hwnd=7788, title="微信", process_name="Weixin.exe", rect=(40, 40, 1240, 840), visible=True)
    )
    services.runtime.set_paused(True)
    window._run_capture_pipeline()
    paused_status = window.statusBar().currentMessage()
    if "用户已暂停采集" not in paused_status:
        raise RuntimeError(f"paused capture feedback is not actionable: {paused_status}")
    runtime_text = window._runtime_text.toPlainText()
    if "capture=False" not in runtime_text or "用户已暂停采集" not in runtime_text:
        raise RuntimeError(f"runtime panel was not refreshed after blocked capture: {runtime_text}")

    print(f"missing={missing_status} paused={paused_status}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
