from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from whochat.capture.policy import CaptureGate
from whochat.core.runtime import CapturePolicy, RuntimeState, missing_runtime_state
from whochat.services.pipeline import PipelineResult
from whochat.platform.adapters import PlatformAdapter, WeChatAdapter
from whochat.platform.window_tracker import WindowInfo


class RuntimeStateService(QObject):
    state_changed = Signal(object)

    def __init__(
        self,
        adapter: PlatformAdapter | None = None,
        capture_policy: CapturePolicy | None = None,
        calibrations=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter or WeChatAdapter(calibrations=calibrations)
        self.capture_gate = CaptureGate(capture_policy or CapturePolicy())
        self._state = missing_runtime_state()
        self._paused = False

    @property
    def state(self) -> RuntimeState:
        return self._state

    def set_paused(self, paused: bool) -> RuntimeState:
        self._paused = paused
        return self.refresh_current()

    def refresh_current(self) -> RuntimeState:
        return self.update_from_window_info(None if self._state.window.hwnd is None else _window_info_from_state(self._state))

    def update_from_window_info(self, window: WindowInfo | None) -> RuntimeState:
        window_snapshot = self.adapter.window_snapshot(window)
        layout = self.adapter.estimate_layout(window_snapshot)
        page = self.adapter.classify_page(window_snapshot, layout)
        provisional = RuntimeState(
            window=window_snapshot,
            layout=layout,
            page=page,
            capture_decision=self._state.capture_decision,
            paused=self._paused,
            last_snapshot_hash=self._state.last_snapshot_hash,
            visible_message_count=self._state.visible_message_count,
            pipeline_status=self._state.pipeline_status,
        )
        decision = self.capture_gate.evaluate(provisional)
        self._state = RuntimeState(
            window=window_snapshot,
            layout=layout,
            page=page,
            capture_decision=decision,
            paused=self._paused,
            last_snapshot_hash=self._state.last_snapshot_hash,
            visible_message_count=self._state.visible_message_count,
            pipeline_status=self._state.pipeline_status,
        )
        self.state_changed.emit(self._state)
        return self._state

    def apply_pipeline_started(self) -> RuntimeState:
        self._state = RuntimeState(
            window=self._state.window,
            layout=self._state.layout,
            page=self._state.page,
            capture_decision=self._state.capture_decision,
            paused=self._state.paused,
            ocr_pending=True,
            ai_pending=self._state.ai_pending,
            last_snapshot_hash=self._state.last_snapshot_hash,
            visible_message_count=self._state.visible_message_count,
            pipeline_status="running",
        )
        self.state_changed.emit(self._state)
        return self._state

    def apply_pipeline_result(self, result: PipelineResult) -> RuntimeState:
        if result.hwnd != self._state.window.hwnd:
            return self._state
        self._state = RuntimeState(
            window=self._state.window,
            layout=self._state.layout,
            page=result.page,
            capture_decision=self._state.capture_decision,
            paused=self._state.paused,
            ocr_pending=False,
            ai_pending=self._state.ai_pending,
            last_snapshot_hash=result.snapshot_hash,
            visible_message_count=len(result.messages),
            pipeline_status=f"finished:{result.page.page_type.value}",
        )
        self.state_changed.emit(self._state)
        return self._state

    def apply_title_result(self, result) -> RuntimeState:
        if result.hwnd != self._state.window.hwnd:
            return self._state
        self._state = RuntimeState(
            window=self._state.window,
            layout=self._state.layout,
            page=self._state.page,
            capture_decision=self._state.capture_decision,
            paused=self._state.paused,
            ocr_pending=True,
            ai_pending=self._state.ai_pending,
            last_snapshot_hash=result.snapshot_hash,
            visible_message_count=self._state.visible_message_count,
            pipeline_status="title_ready",
        )
        self.state_changed.emit(self._state)
        return self._state

    def apply_pipeline_discarded(self, reason: str) -> RuntimeState:
        self._state = RuntimeState(
            window=self._state.window,
            layout=self._state.layout,
            page=self._state.page,
            capture_decision=self._state.capture_decision,
            paused=self._state.paused,
            ocr_pending=False,
            ai_pending=self._state.ai_pending,
            last_snapshot_hash=self._state.last_snapshot_hash,
            visible_message_count=self._state.visible_message_count,
            pipeline_status=f"discarded:{reason}",
        )
        self.state_changed.emit(self._state)
        return self._state


def _window_info_from_state(state: RuntimeState) -> WindowInfo | None:
    if state.window.hwnd is None or state.window.rect is None:
        return None
    return WindowInfo(
        hwnd=state.window.hwnd,
        title=state.window.title,
        process_name=state.window.process_name,
        rect=state.window.rect.as_tuple(),
        visible=True,
        target_app=state.window.target.value,
        app_label=state.window.app_label,
        diagnostic=state.window.diagnostic,
        foreground=state.window.foreground,
        bubble_profile=state.window.bubble_profile,
    )
