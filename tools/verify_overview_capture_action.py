from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "overview_capture_action_verify"
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
    services.runtime.update_from_window_info(
        WindowInfo(hwnd=9090, title="微信", process_name="Weixin.exe", rect=(0, 0, 1200, 800), visible=True)
    )
    window._refresh_overview_data()
    if window._overview_capture_button is None or window._overview_capture_button.isHidden():
        raise RuntimeError("overview should expose immediate capture action when WeChat window awaits OCR confirmation")
    status_text = window._overview_next_action.text()
    if "立即采集" not in status_text:
        raise RuntimeError(f"overview next action should guide capture, got: {status_text}")
    if "仅从窗口标题无法确认" in status_text:
        raise RuntimeError(f"overview should not show stale title-only wording: {status_text}")
    print(f"button={window._overview_capture_button.text()} action={status_text}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
