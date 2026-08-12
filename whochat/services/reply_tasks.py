from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from whochat.ai.models import ReplyContext, ReplyGenerationResult
from whochat.config import AppConfig
from whochat.services.reply import ReplyGenerationService


@dataclass(frozen=True)
class ReplyTaskResult:
    job_id: int
    result: ReplyGenerationResult
    contact_id: str | None = None
    hwnd: int | None = None
    window_title: str = ""


class ReplyTaskService(QObject):
    result_ready = Signal(object)
    result_discarded = Signal(str)
    status_changed = Signal(str)

    def __init__(
        self,
        generator: ReplyGenerationService,
        executor: ThreadPoolExecutor | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.generator = generator
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="whochat-reply")
        self._job_id = 0
        self._latest_job_id = 0
        self._running: Future | None = None
        self.last_result: ReplyTaskResult | None = None
        self.last_status = "idle"
        self.last_discard_reason: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running is not None and not self._running.done()

    def shutdown(self) -> None:
        if self._running is not None and not self._running.done():
            self._running.cancel()
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.executor.shutdown(wait=False)
        self._set_status("reply_shutdown")

    def submit(self, context: ReplyContext, config: AppConfig) -> int | None:
        if self.is_running:
            self._discard("reply_generation_busy")
            return None

        self._job_id += 1
        self._latest_job_id = self._job_id
        job_id = self._job_id
        self._set_status(f"reply_started: job={job_id}")
        frozen_config = deepcopy(config)
        self._running = self.executor.submit(self._run_job, job_id, context, frozen_config)
        self._running.add_done_callback(self._on_done)
        return job_id

    def run_sync(self, context: ReplyContext, config: AppConfig) -> ReplyTaskResult | None:
        job_id = self.submit(context, config)
        if job_id is None or self._running is None:
            return None
        return self._running.result(timeout=config.ai.timeout_seconds + 5)

    def _run_job(self, job_id: int, context: ReplyContext, config: AppConfig) -> ReplyTaskResult:
        return ReplyTaskResult(
            job_id=job_id,
            result=self.generator.generate(context, config),
            contact_id=context.contact.id if context.contact else None,
            hwnd=context.runtime.window.hwnd,
            window_title=context.runtime.window.title,
        )

    def _on_done(self, future: Future) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self._discard(f"reply_failed:{exc}")
            return
        if result.job_id != self._latest_job_id:
            self._discard(f"reply_stale_result:{result.job_id}")
            return
        self.last_result = result
        self._set_status(
            f"reply_finished: job={result.job_id}, allowed={result.result.allowed}, status={result.result.status}"
        )
        self.result_ready.emit(result)

    def _discard(self, reason: str) -> None:
        self.last_discard_reason = reason
        self.result_discarded.emit(reason)

    def _set_status(self, status: str) -> None:
        self.last_status = status
        self.status_changed.emit(status)
