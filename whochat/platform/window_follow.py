from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from whochat.config import TargetWindowConfig, default_target_windows
from whochat.platform.window_tracker import WindowInfo, find_target_windows, find_wechat_windows, foreground_window_handle


class TargetWindowFollowController(QObject):
    window_changed = Signal(object)
    status_changed = Signal(str)

    def __init__(
        self,
        targets: list[TargetWindowConfig] | None = None,
        interval_ms: int = 800,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.targets = targets or default_target_windows()
        self._last_hwnd: int | None = None
        self._last_signature: tuple[int, str, tuple[int, int, int, int], bool] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll_once)

    def start(self) -> None:
        self._timer.start()
        self.poll_once()

    def stop(self) -> None:
        self._timer.stop()

    def set_targets(self, targets: list[TargetWindowConfig]) -> None:
        self.targets = targets
        self._last_hwnd = None
        self._last_signature = None
        self.poll_once()

    def poll_once(self) -> WindowInfo | None:
        windows = find_target_windows(self.targets)
        if not windows:
            self._last_hwnd = None
            self._last_signature = None
            self.status_changed.emit("未发现已启用的聊天窗口")
            self.window_changed.emit(None)
            return None
        focused = foreground_window_handle()
        window = next((item for item in windows if item.hwnd == focused), None)
        if window is None:
            window = max(windows, key=lambda item: (item.rect[2] - item.rect[0]) * (item.rect[3] - item.rect[1]))
        signature = (window.hwnd, window.title, window.rect, window.visible)
        if signature == self._last_signature:
            return window
        self._last_signature = signature
        if window.hwnd != self._last_hwnd:
            self.status_changed.emit(f"已连接：{window.app_label} · {window.title}")
            self._last_hwnd = window.hwnd
        self.window_changed.emit(window)
        return window


class WeChatFollowController(TargetWindowFollowController):
    def __init__(self, interval_ms: int = 800, parent: QObject | None = None) -> None:
        targets = [target for target in default_target_windows() if target.app_id == "wechat"]
        super().__init__(targets=targets, interval_ms=interval_ms, parent=parent)
