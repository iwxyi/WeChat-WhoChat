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
import whochat.platform.window_follow as window_follow


def main() -> int:
    QCoreApplication.instance() or QCoreApplication(sys.argv)
    target = TargetWindowConfig("wechat", "微信", True, ["Weixin.exe"], ["微信"], [])
    foreground = WindowInfo(700, "微信", "Weixin.exe", (10, 10, 900, 700), True, "wechat", "微信", foreground=True)
    background = WindowInfo(
        700,
        "微信",
        "Weixin.exe",
        (10, 10, 900, 700),
        True,
        "wechat",
        "微信",
        foreground=False,
        diagnostic="后台测试模式：目标窗口不是前台，截图可能被遮挡",
    )
    sequence = [[foreground], [background]]
    original_find = window_follow.find_target_windows
    original_foreground = window_follow.foreground_window_handle
    try:
        window_follow.find_target_windows = lambda _targets: sequence.pop(0)
        window_follow.foreground_window_handle = lambda: 700 if sequence else 999
        controller = TargetWindowFollowController([target], foreground_only=False)
        emitted: list[WindowInfo | None] = []
        controller.window_changed.connect(emitted.append)
        controller.poll_once()
        controller.poll_once()
    finally:
        window_follow.find_target_windows = original_find
        window_follow.foreground_window_handle = original_foreground
    if len(emitted) != 2:
        raise RuntimeError(f"foreground transition with unchanged rect was suppressed: {emitted}")
    if emitted[-1] is None or emitted[-1].foreground or "后台测试模式" not in emitted[-1].diagnostic:
        raise RuntimeError(f"background safety state was not propagated: {emitted[-1]}")
    print(f"emissions={len(emitted)} foreground={emitted[0].foreground}->{emitted[1].foreground}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
