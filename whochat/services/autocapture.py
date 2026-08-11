from __future__ import annotations

import os
import time
from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from whochat.core.models import CaptureSample
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.pipeline = pipeline
        self.enabled = enabled
        self._pending = False
        self._pending_state: RuntimeState | None = None
        self._last_submit_job_id: int | None = None
        self._last_completed_ms = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush_pending)
        result_ready = getattr(self.pipeline, "result_ready", None)
        if result_ready is not None:
            result_ready.connect(lambda _result: self._on_pipeline_completed("finished"))
        result_discarded = getattr(self.pipeline, "result_discarded", None)
        if result_discarded is not None:
            result_discarded.connect(self._on_pipeline_discarded)

    @property
    def pending(self) -> bool:
        return self._pending

    @property
    def last_submit_job_id(self) -> int | None:
        return self._last_submit_job_id

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self._pending = False
            self._pending_state = None
            self._timer.stop()
            self.status_changed.emit("auto_capture_disabled")
        else:
            self.status_changed.emit("auto_capture_enabled")

    def on_window_changed(self, window: WindowInfo | None) -> None:
        state = self.runtime.update_from_window_info(window)
        if not self.enabled:
            return
        if not state.capture_decision.should_capture:
            if not (self._pending and _is_transient_capture_block(state.capture_decision.reason)):
                self._pending = False
                self._pending_state = None
                self._timer.stop()
            self.status_changed.emit(f"auto_capture_blocked:{state.capture_decision.reason}")
            return
        self._pending = True
        self._pending_state = state
        delay_ms = max(0, self.runtime.capture_gate.policy.scroll_debounce_ms)
        self._timer.start(delay_ms)
        self.status_changed.emit(f"auto_capture_pending:{delay_ms}ms")

    def flush_pending(self) -> int | None:
        if not self.enabled or not self._pending:
            return None
        self._pending = False
        state = self._pending_state
        self._pending_state = None
        if state is None:
            self.status_changed.emit("auto_capture_skipped:no_pending_state")
            return None
        if not state.capture_decision.should_capture:
            self.status_changed.emit(f"auto_capture_skipped:{state.capture_decision.reason}")
            return None
        if self.pipeline.is_running:
            self._pending = True
            self._pending_state = state
            self.status_changed.emit("auto_capture_skipped:pipeline_running")
            return None
        now_ms = int(time.monotonic() * 1000)
        elapsed = now_ms - self._last_completed_ms if self._last_completed_ms else None
        min_interval = max(self.runtime.capture_gate.policy.ocr_min_interval_ms, 2500)
        if getattr(getattr(self.pipeline, "ocr_engine", None), "name", "") == "paddleocr":
            min_interval = max(min_interval, _heavy_ocr_min_interval_ms())
        perf_policy = _recent_ocr_performance_policy(_read_recent_capture_samples(self.pipeline), min_interval)
        min_interval = perf_policy.min_interval_ms
        if elapsed is not None and elapsed < min_interval:
            self._pending = True
            self._pending_state = state
            remaining = max(1, min_interval - elapsed)
            self._timer.start(remaining)
            if perf_policy.status == "ok":
                self.status_changed.emit(f"auto_capture_waiting:flow_cooldown:{elapsed}ms<{min_interval}ms")
            else:
                self.status_changed.emit(
                    f"auto_capture_waiting:ocr_perf_{perf_policy.status}:{elapsed}ms<{min_interval}ms"
                )
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
        self._on_pipeline_completed(f"discarded:{reason}")

    def _on_pipeline_completed(self, reason: str) -> None:
        self._last_completed_ms = int(time.monotonic() * 1000)
        if self.enabled and self._pending and not self._timer.isActive():
            delay_ms = max(0, self.runtime.capture_gate.policy.ocr_min_interval_ms)
            if getattr(getattr(self.pipeline, "ocr_engine", None), "name", "") == "paddleocr":
                delay_ms = max(delay_ms, _heavy_ocr_min_interval_ms())
            self._timer.start(delay_ms)
            self.status_changed.emit(f"auto_capture_pending_after_{reason}:{delay_ms}ms")


def _is_transient_capture_block(reason: str) -> bool:
    return reason.startswith("截图节流中") or reason.startswith("窗口区域刚变化")


def _heavy_ocr_min_interval_ms() -> int:
    try:
        return max(5000, int(os.environ.get("WHOCHAT_HEAVY_OCR_MIN_INTERVAL_MS", "5000")))
    except ValueError:
        return 5000


@dataclass(frozen=True)
class OcrPerformancePolicy:
    status: str
    avg_total_ms: int | None
    min_interval_ms: int


def _read_recent_capture_samples(pipeline: CapturePipelineService) -> list[CaptureSample]:
    repository = getattr(pipeline, "capture_samples", None)
    if repository is None:
        return []
    try:
        return list(repository.tail(8))
    except Exception:
        return []


def _recent_ocr_performance_policy(samples: Iterable[CaptureSample], base_min_interval_ms: int) -> OcrPerformancePolicy:
    totals = [
        sample.total_elapsed_ms
        for sample in samples
        if sample.total_elapsed_ms is not None
        and sample.total_elapsed_ms > 0
        and "paddle" in sample.ocr_engine.lower()
    ]
    if len(totals) < 2:
        return OcrPerformancePolicy("ok", None, base_min_interval_ms)
    avg_total_ms = round(sum(totals) / len(totals))
    if avg_total_ms <= 15000:
        return OcrPerformancePolicy("ok", avg_total_ms, base_min_interval_ms)
    if avg_total_ms <= 45000:
        interval = max(base_min_interval_ms, avg_total_ms * 2)
        return OcrPerformancePolicy("warning", avg_total_ms, _bounded_perf_interval(interval))
    interval = max(base_min_interval_ms, avg_total_ms * 3, _slow_ocr_min_interval_ms())
    return OcrPerformancePolicy("slow", avg_total_ms, _bounded_perf_interval(interval))


def _slow_ocr_min_interval_ms() -> int:
    try:
        return max(60000, int(os.environ.get("WHOCHAT_SLOW_OCR_MIN_INTERVAL_MS", "120000")))
    except ValueError:
        return 120000


def _bounded_perf_interval(interval_ms: int) -> int:
    return min(max(interval_ms, 2500), 300000)
