from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "window_match_diagnostics_ui_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from whochat.app import create_app
from whochat.platform.window_tracker import WindowMatchDiagnostic
from whochat.services.bootstrap import build_services
import whochat.ui.main_window as main_window
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    window = MainWindow(services)

    original_diagnose = main_window.diagnose_target_windows
    original_foreground = main_window.foreground_window_handle
    try:
        main_window.foreground_window_handle = lambda: 2
        main_window.diagnose_target_windows = lambda _targets, limit=12: [
            WindowMatchDiagnostic(1, "微信", "Weixin.exe", 1001, True, "wechat", "微信", "matched_by_process", False),
            WindowMatchDiagnostic(2, "Telegram", "Telegram.exe", 1002, True, "telegram", "Telegram", "matched_by_process", True),
        ]
        focused = window._format_window_match_diagnostics()
        if "foreground=True" not in focused or "当前前台已命中" not in focused:
            raise RuntimeError(f"focused diagnostic missing actionable state: {focused}")

        main_window.diagnose_target_windows = lambda _targets, limit=12: [
            WindowMatchDiagnostic(3, "图片和视频", "Weixin.exe", 1003, False, "wechat", "微信", "excluded_by_title", True),
            WindowMatchDiagnostic(1, "微信", "Weixin.exe", 1001, True, "wechat", "微信", "matched_by_process", False),
        ]
        excluded = window._format_window_match_diagnostics()
        if "excluded_by_title" not in excluded or "非聊天子窗口" not in excluded or "排除规则" not in excluded:
            raise RuntimeError(f"excluded diagnostic missing actionable state: {excluded}")

        main_window.foreground_window_handle = lambda: 999
        main_window.diagnose_target_windows = lambda _targets, limit=12: [
            WindowMatchDiagnostic(1, "微信", "Weixin.exe", 1001, True, "wechat", "微信", "matched_by_process", False),
        ]
        background = window._format_window_match_diagnostics()
        if "不在前台" not in background or "截图和 OCR" not in background:
            raise RuntimeError(f"background diagnostic missing actionable state: {background}")

        main_window.diagnose_target_windows = lambda _targets, limit=12: [
            WindowMatchDiagnostic(
                4,
                "微信 13812345678 sk-window-secret-token-value",
                "Weixin.exe",
                1004,
                True,
                "wechat",
                "微信",
                "matched_by_process",
                True,
            ),
        ]
        window._refresh_window_match_diagnostics()
        refreshed = window._window_match_text.toPlainText()
        if "hwnd=4" not in refreshed or "当前前台已命中" not in refreshed:
            raise RuntimeError(f"refresh action did not update window diagnostics: {refreshed}")
        window._copy_window_match_diagnostics()
        clipboard = QApplication.clipboard().text()
        if "# runtime" in clipboard or "# files" in clipboard:
            raise RuntimeError(f"window copy should only include window diagnostics: {clipboard}")
        if "13812345678" in clipboard or "sk-window-secret-token-value" in clipboard:
            raise RuntimeError(f"window diagnostics copy leaked sensitive title text: {clipboard}")
        if "[已脱敏:手机号]" not in clipboard or "[已脱敏:密钥]" not in clipboard:
            raise RuntimeError(f"window diagnostics copy missing redaction markers: {clipboard}")
    finally:
        main_window.diagnose_target_windows = original_diagnose
        main_window.foreground_window_handle = original_foreground

    print("window_match_diagnostics_ui=ok")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
