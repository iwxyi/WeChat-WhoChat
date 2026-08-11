from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "floating_follow_behavior_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import _sync_floating, create_app
from whochat.platform.window_tracker import WindowInfo
from whochat.ui.floating_widget import FloatingWidget


def main() -> int:
    app = create_app()
    floating = FloatingWidget()
    floating.update_context(
        app_label="微信",
        contact_name="跟随验证对象",
        group_name="默认",
        status="AI:就绪",
        action="点击生成建议",
    )
    floating.attach_to_window_rect((100, 100, 900, 720), "微信")
    if floating.status_label.text() != "AI:就绪":
        raise RuntimeError(f"placement should not overwrite business status: {floating.status_label.text()}")
    if floating.placement_edge not in {"底部", "顶部", "右侧", "左侧"}:
        raise RuntimeError(f"placement edge was not recorded: {floating.placement_edge}")
    if "贴靠目标窗口" not in floating.status_label.toolTip():
        raise RuntimeError(f"placement tooltip missing: {floating.status_label.toolTip()}")
    _sync_floating(
        floating,
        WindowInfo(
            hwnd=66,
            title="微信",
            process_name="Weixin.exe",
            rect=(100, 100, 900, 720),
            visible=True,
            target_app="wechat",
            app_label="微信",
        ),
        color_sampler=lambda _rect: (32, 80, 72),
    )
    if "#floatingroot" not in floating.root.styleSheet().lower():
        raise RuntimeError("floating widget should apply sampled window color stylesheet")

    floating.hide_by_user()
    floating.attach_to_window_rect((120, 120, 920, 740), "微信")
    if floating.isVisible():
        raise RuntimeError("user-hidden floating widget should not reappear on window move")

    floating.show_by_user()
    if not floating.isVisible():
        raise RuntimeError("show_by_user should restore floating widget when target rect is known")

    minimized = WindowInfo(
        hwnd=77,
        title="微信",
        process_name="Weixin.exe",
        rect=(100, 100, 900, 720),
        visible=False,
        target_app="wechat",
        app_label="微信",
        minimized=True,
        diagnostic="目标窗口已最小化，悬浮窗和采集会暂停",
    )
    _sync_floating(floating, minimized)
    if floating.isVisible() or floating.placement_edge:
        raise RuntimeError("minimized target should hide floating widget and clear placement edge")
    floating.show_waiting()
    _sync_floating(floating, None)
    if floating.isVisible() or floating.placement_edge:
        raise RuntimeError("missing target should hide floating widget")

    print(f"status={floating.status_label.text()} edge={floating.placement_edge or '-'}")
    floating.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
