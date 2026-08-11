from __future__ import annotations

import sys
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PIL import ImageGrab

from whochat.diagnostics import configure_native_runtime_limits, configure_process_diagnostics
from whochat.config import ConfigStore
from whochat.platform.window_follow import TargetWindowFollowController
from whochat.services.bootstrap import build_services
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow
from whochat.ui.theme import apply_app_theme


def create_app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("WhoChat")
    app.setOrganizationName("WhoChat")
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    apply_app_theme(app)
    return app


def main() -> int:
    configure_native_runtime_limits()
    crash_log = configure_process_diagnostics()
    app = create_app()
    config = ConfigStore().load()
    services = build_services()
    main_window = MainWindow(services)
    main_window.append_log(f"diagnostics_log: {crash_log}")
    floating = FloatingWidget()
    floating.apply_preferences(
        placement_preference=config.floating.placement_preference,
        opacity_percent=config.floating.opacity_percent,
        suggestion_count=config.floating.suggestion_count,
    )
    follower = TargetWindowFollowController(config.targets, foreground_only=config.capture.foreground_only)
    main_window.attach_floating_widget(floating)
    main_window.targets_changed.connect(follower.set_targets)
    main_window.capture_mode_changed.connect(follower.set_foreground_only)
    follower.window_changed.connect(services.autocapture.on_window_changed)
    follower.window_changed.connect(lambda window: _sync_floating(floating, window))
    follower.status_changed.connect(main_window.append_log)
    services.autocapture.status_changed.connect(main_window.append_log)
    app.aboutToQuit.connect(follower.stop)
    app.aboutToQuit.connect(services.shutdown)
    app.aboutToQuit.connect(floating.close)
    main_window.show()
    follower.start()
    return app.exec()


def _sync_floating(
    floating: FloatingWidget,
    window,
    color_sampler: Callable[[tuple[int, int, int, int]], tuple[int, int, int] | None] | None = None,
) -> None:
    if window is None:
        floating.hide_for_window_state("未发现已启用的聊天窗口")
        return
    if getattr(window, "minimized", False) or not getattr(window, "visible", True) or not getattr(window, "foreground", True):
        floating.hide_for_window_state(getattr(window, "diagnostic", "") or "目标窗口不可见")
        return
    if hasattr(floating, "apply_window_color"):
        sampler = color_sampler or _average_window_color
        floating.apply_window_color(sampler(window.rect))
    floating.attach_to_window_rect(window.rect, window.title)


def _average_window_color(rect: tuple[int, int, int, int]) -> tuple[int, int, int] | None:
    left, top, right, bottom = rect
    width = max(1, right - left)
    height = max(1, bottom - top)
    sample_rect = (
        left + round(width * 0.36),
        top + round(height * 0.12),
        left + round(width * 0.96),
        top + round(height * 0.82),
    )
    try:
        image = ImageGrab.grab(bbox=sample_rect).convert("RGB").resize((1, 1))
        pixel = image.getpixel((0, 0))
    except Exception:
        return None
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


if __name__ == "__main__":
    raise SystemExit(main())
