from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "window_diagnostics_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import _sync_floating, create_app
from whochat.config import AppConfig
from whochat.core.runtime import WindowState
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.status import build_status_chain
from whochat.ui.floating_widget import FloatingWidget


def main() -> int:
    app = create_app()
    services = build_services()

    minimized = WindowInfo(
        hwnd=77,
        title="微信",
        process_name="WeChat.exe",
        rect=(0, 0, 1200, 800),
        visible=False,
        target_app="wechat",
        app_label="微信",
        process_id=1000,
        minimized=True,
        diagnostic="目标窗口已最小化，悬浮窗和采集会暂停",
    )
    state = services.runtime.update_from_window_info(minimized)
    if state.window.state != WindowState.MINIMIZED:
        raise RuntimeError(f"minimized window state mismatch: {state.window.state}")
    if state.capture_decision.should_capture:
        raise RuntimeError("minimized window should block capture")
    chain = build_status_chain(
        runtime=state,
        contact=None,
        strategy=None,
        config=AppConfig(),
        reply_running=False,
        provider_health="status=ok",
    )
    window_step = next(step for step in chain if step.stage == "窗口")
    if "最小化" not in window_step.reason:
        raise RuntimeError(f"window status should explain minimized state: {window_step}")

    floating = FloatingWidget()
    floating.show_waiting()
    _sync_floating(floating, minimized)
    if floating.isVisible():
        raise RuntimeError("floating widget should hide for minimized target")

    background = WindowInfo(
        hwnd=78,
        title="微信",
        process_name="Weixin.exe",
        rect=(0, 0, 1200, 800),
        visible=False,
        target_app="wechat",
        app_label="微信",
        process_id=1001,
        diagnostic="目标窗口不是当前前景窗口；屏幕截图会被上层窗口遮挡，已暂停采集",
        foreground=False,
    )
    background_state = services.runtime.update_from_window_info(background)
    if background_state.window.state != WindowState.UNAVAILABLE:
        raise RuntimeError(f"background target should be unavailable: {background_state.window.state}")
    if background_state.capture_decision.should_capture:
        raise RuntimeError("background target should block capture")
    if "前景窗口" not in background_state.window.diagnostic:
        raise RuntimeError(f"background diagnostic missing foreground hint: {background_state.window.diagnostic}")
    floating.show_waiting()
    _sync_floating(floating, background)
    if floating.isVisible():
        raise RuntimeError("floating widget should hide for background target")

    title_only = WindowInfo(
        hwnd=88,
        title="Slack - Team",
        process_name="",
        rect=(0, 0, 1100, 760),
        visible=True,
        target_app="generic_chat",
        app_label="Slack",
        diagnostic="仅通过窗口标题匹配，未读取到目标进程名；若采集失败，请检查权限或补充进程名规则",
    )
    title_state = services.runtime.update_from_window_info(title_only)
    if title_state.window.state != WindowState.VISIBLE:
        raise RuntimeError("title-only visible window should remain visible")
    if "标题匹配" not in title_state.window.diagnostic:
        raise RuntimeError(f"title-only diagnostic missing: {title_state.window.diagnostic}")
    print(
        f"minimized={state.window.state.value} background={background_state.window.state.value} "
        f"visible_diag={title_state.window.diagnostic[:18]}"
    )
    floating.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
