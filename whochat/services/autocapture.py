from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from whochat.core.runtime import RuntimeState
from whochat.platform.window_tracker import WindowInfo
from whochat.services.pipeline import CapturePipelineService
from whochat.services.runtime import RuntimeStateService


class AutoCaptureController(QObject):
    status_changed = Signal(str)

    def __init__(
        self,
        runtime: RuntimeStateService,
        pipeline: CapturePipelineService,
        *,
        enabled: bool = True,
        interval_ms: int = 5000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.pipeline = pipeline
        self.enabled = enabled
        self.interval_ms = max(1000, int(interval_ms))
        self._pending_state: RuntimeState | None = None
        self._last_submit_job_id: int | None = None
        self._last_window: WindowInfo | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.interval_ms)
        self._timer.timeout.connect(self._run_cycle)
        result_ready = getattr(self.pipeline, "result_ready", None)
        if result_ready is not None:
            result_ready.connect(lambda _result: self.status_changed.emit("auto_capture_flow_finished:finished"))
        result_discarded = getattr(self.pipeline, "result_discarded", None)
        if result_discarded is not None:
            result_discarded.connect(self._on_pipeline_discarded)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self._run_cycle()

    def stop(self) -> None:
        self._timer.stop()
        self._pending_state = None

    @property
    def pending(self) -> bool:
        return self._pending_state is not None

    @property
    def last_submit_job_id(self) -> int | None:
        return self._last_submit_job_id

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self._pending_state = None
            self._last_window = None
            self._timer.stop()
            self.status_changed.emit("auto_capture_disabled")
        else:
            self._timer.start(self.interval_ms)
            self.status_changed.emit("auto_capture_enabled")

    def on_window_changed(self, window: WindowInfo | None) -> None:
        self._last_window = window
        if not self.enabled:
            return
        self.status_changed.emit("auto_capture_window_updated")

    def _run_cycle(self) -> None:
        if not self.enabled or self._last_window is None:
            return
        state = self.runtime.update_from_window_info(self._last_window)
        if not state.capture_decision.should_capture:
            self._pending_state = None
            self.status_changed.emit(f"auto_capture_blocked:{state.capture_decision.reason}")
            return
        self._pending_state = state
        self.status_changed.emit("auto_capture_cycle")
        self.flush_pending()

    def flush_pending(self) -> int | None:
        if not self.enabled or self._pending_state is None:
            return None
        state = self._pending_state
        self._pending_state = None
        if self.pipeline.is_running:
            self._pending_state = state
            self.status_changed.emit("auto_capture_skipped:pipeline_running")
            return None
        job_id = self.pipeline.submit(state)
        self._last_submit_job_id = job_id
        if job_id is None:
            self.status_changed.emit("auto_capture_submit_failed")
        else:
            self.status_changed.emit(f"auto_capture_submitted:{job_id}")
        return job_id

    def _on_pipeline_discarded(self, reason: str) -> None:
        if reason.startswith(("pipeline_busy", "stale_result", "superseded_running_job")):
            return
        self.status_changed.emit(f"auto_capture_flow_finished:discarded:{reason}")
