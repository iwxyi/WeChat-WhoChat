from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication

from whochat.config import TargetWindowConfig
from whochat.platform.window_follow import TargetWindowFollowController
from whochat.platform.window_tracker import WindowInfo


def main() -> int:
    QCoreApplication.instance() or QCoreApplication(sys.argv)
    target = TargetWindowConfig("wechat", "微信", True, ["Weixin.exe"], ["微信"], [])
    background = WindowInfo(
        hwnd=1001,
        title="微信",
        process_name="Weixin.exe",
        rect=(10, 10, 900, 700),
        visible=False,
        target_app="wechat",
        app_label="微信",
        foreground=False,
    )
    selected: list[WindowInfo | None] = []
    controller = TargetWindowFollowController([target], foreground_only=True)
    controller.window_changed.connect(selected.append)
    controller.poll_once = lambda: None  # type: ignore[method-assign]

    strict = _select_window([background], focused=2002, foreground_only=True)
    if strict is not None:
        raise RuntimeError(f"strict foreground mode should ignore background target: {strict}")
    relaxed = _select_window([background], focused=2002, foreground_only=False)
    if relaxed is None or not relaxed.visible or relaxed.foreground or "后台测试模式" not in relaxed.diagnostic:
        raise RuntimeError(f"relaxed foreground mode should return background test window: {relaxed}")
    print(f"strict={strict} relaxed={relaxed.hwnd} diagnostic={relaxed.diagnostic}")
    return 0


def _select_window(windows: list[WindowInfo], *, focused: int | None, foreground_only: bool) -> WindowInfo | None:
    window = next((item for item in windows if item.hwnd == focused), None)
    if window is not None:
        return window
    if foreground_only:
        return None
    from whochat.platform.window_follow import _as_background_test_window

    return _as_background_test_window(max(windows, key=lambda item: (item.rect[2] - item.rect[0]) * (item.rect[3] - item.rect[1])))


if __name__ == "__main__":
    raise SystemExit(main())
