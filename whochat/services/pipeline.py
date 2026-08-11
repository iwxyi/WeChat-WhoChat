from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time

from PIL import Image
from PySide6.QtCore import QObject, Signal

from whochat.capture.policy import image_hash
from whochat.capture.screenshot import capture_rect
from whochat.core.models import utc_now_iso
from whochat.core.paths import app_data_dir
from whochat.core.runtime import LayoutRegions, PageClassification, Rect, RuntimeState
from whochat.diagnostics import append_diagnostics_log
from whochat.ocr.engine import OcrEngine, PreviewOcrEngine
from whochat.ocr.models import OcrResult, OcrTextBox, ParsedOcrMessage
from whochat.ocr.parser import classify_page_from_ocr, parse_visible_messages
from whochat.storage.repositories import CaptureSampleRepository


@dataclass(frozen=True)
class PipelineResult:
    job_id: int
    hwnd: int | None
    target_app: str
    app_label: str
    snapshot_hash: str
    image_path: Path
    ocr_image_path: Path
    crop_rect: Rect | None
    layout: LayoutRegions
    ocr_result: OcrResult
    page: PageClassification
    messages: list[ParsedOcrMessage]
    created_at: str
    title_ocr_image_path: Path | None = None
    title_crop_rect: Rect | None = None
    title_ocr_elapsed_ms: int | None = None
    content_ocr_elapsed_ms: int | None = None
    total_elapsed_ms: int | None = None


@dataclass(frozen=True)
class TitleOcrResult:
    job_id: int
    hwnd: int | None
    target_app: str
    app_label: str
    snapshot_hash: str
    image_path: Path
    title_ocr_image_path: Path
    title_crop_rect: Rect | None
    layout: LayoutRegions
    ocr_result: OcrResult
    created_at: str
    elapsed_ms: int | None = None


class CapturePipelineService(QObject):
    title_ready = Signal(object)
    result_ready = Signal(object)
    result_discarded = Signal(str)
    status_changed = Signal(str)

    def __init__(
        self,
        ocr_engine: OcrEngine | None = None,
        capture_func=None,
        executor: ThreadPoolExecutor | None = None,
        capture_samples: CaptureSampleRepository | None = None,
        retain_capture_images: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.ocr_engine = ocr_engine or PreviewOcrEngine()
        self.capture_func = capture_func or capture_rect
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="whochat-capture")
        self.capture_samples = capture_samples
        self.retain_capture_images = retain_capture_images
        self._job_id = 0
        self._latest_job_id = 0
        self._running: Future | None = None
        self._running_job_id: int | None = None
        self._last_snapshot_hash: str | None = None
        self.last_result: PipelineResult | None = None
        self.last_title_result: TitleOcrResult | None = None
        self.last_discard_reason: str | None = None
        self.last_status: str = "idle"

    @property
    def is_running(self) -> bool:
        return self._running is not None and not self._running.done()

    def shutdown(self) -> None:
        if self._running is not None and not self._running.done():
            self._running.cancel()
        shutdown = getattr(self.ocr_engine, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception as exc:
                append_diagnostics_log("capture_pipeline", f"ocr_engine_shutdown_failed error={exc}")
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.executor.shutdown(wait=False)
        except Exception as exc:
            append_diagnostics_log("capture_pipeline", f"executor_shutdown_failed error={exc}")
        self._set_status("pipeline_shutdown")

    def submit(self, state: RuntimeState) -> int | None:
        if state.layout is None or state.window.rect is None:
            self._discard("layout_unavailable")
            return None
        if not state.capture_decision.should_capture:
            self._discard(state.capture_decision.reason)
            return None
        heavy_ocr = getattr(self.ocr_engine, "name", "") == "paddleocr"
        if self._running and not self._running.done():
            if heavy_ocr:
                self._discard(f"pipeline_busy:job={self._running_job_id or '-'}")
                return None
            self._running.cancel()
            self._discard("superseded_running_job")
        self._job_id += 1
        self._latest_job_id = self._job_id
        job_id = self._job_id
        self._running_job_id = job_id
        self._set_status(f"pipeline_started: job={job_id}")
        append_diagnostics_log("capture_pipeline", f"started job={job_id} hwnd={state.window.hwnd} ocr={self.ocr_engine.name}")
        self._running = self.executor.submit(self._run_job, job_id, state)
        self._running.add_done_callback(self._on_done)
        return job_id

    def run_sync(self, state: RuntimeState) -> PipelineResult | None:
        job_id = self.submit(state)
        if job_id is None or self._running is None:
            return None
        try:
            result = self._running.result(timeout=30)
        except DuplicateSnapshotError as exc:
            self._discard(f"duplicate_snapshot:{exc.snapshot_hash}")
            append_diagnostics_log("capture_pipeline", f"sync_discarded duplicate_snapshot={exc.snapshot_hash}")
            return None
        except Exception as exc:
            self._discard(f"pipeline_failed:{exc}")
            append_diagnostics_log("capture_pipeline", f"sync_failed error={exc}")
            return None
        return result

    def _run_job(self, job_id: int, state: RuntimeState) -> PipelineResult:
        job_started = time.monotonic()
        if state.layout is None or state.window.rect is None:
            raise RuntimeError("pipeline requires layout and window rect")
        output = app_data_dir() / "capture" / f"job_{job_id}.png"
        image_path = self.capture_func(state.window.rect.as_tuple(), output)
        snapshot_hash = image_hash(image_path)
        if self._last_snapshot_hash == snapshot_hash:
            raise DuplicateSnapshotError(snapshot_hash)
        self._last_snapshot_hash = snapshot_hash
        title_ocr_image_path, title_layout, title_offset, title_crop_rect = _prepare_title_ocr_input(image_path, state.layout)
        title_started = time.monotonic()
        title_ocr_result = _offset_ocr_result(self.ocr_engine.recognize(title_ocr_image_path, title_layout), title_offset)
        title_elapsed_ms = _elapsed_ms(title_started)
        created_at = utc_now_iso()
        title_result = TitleOcrResult(
            job_id=job_id,
            hwnd=state.window.hwnd,
            target_app=state.window.target.value,
            app_label=state.window.app_label,
            snapshot_hash=snapshot_hash,
            image_path=image_path,
            title_ocr_image_path=title_ocr_image_path,
            title_crop_rect=title_crop_rect,
            layout=state.layout,
            ocr_result=title_ocr_result,
            created_at=created_at,
            elapsed_ms=title_elapsed_ms,
        )
        self.last_title_result = title_result
        self.title_ready.emit(title_result)
        ocr_image_path, ocr_layout, offset, crop_rect = _prepare_ocr_input(image_path, state.layout)
        content_started = time.monotonic()
        content_ocr_result = _offset_ocr_result(self.ocr_engine.recognize(ocr_image_path, ocr_layout), offset)
        content_elapsed_ms = _elapsed_ms(content_started)
        ocr_result = _merge_ocr_results(title_ocr_result, content_ocr_result)
        page = classify_page_from_ocr(ocr_result, state.layout)
        messages = parse_visible_messages(ocr_result, state.layout)
        return PipelineResult(
            job_id=job_id,
            hwnd=state.window.hwnd,
            target_app=state.window.target.value,
            app_label=state.window.app_label,
            snapshot_hash=snapshot_hash,
            image_path=image_path,
            ocr_image_path=ocr_image_path,
            crop_rect=crop_rect,
            layout=state.layout,
            ocr_result=ocr_result,
            page=page,
            messages=messages,
            created_at=created_at,
            title_ocr_image_path=title_ocr_image_path,
            title_crop_rect=title_crop_rect,
            title_ocr_elapsed_ms=title_elapsed_ms,
            content_ocr_elapsed_ms=content_elapsed_ms,
            total_elapsed_ms=_elapsed_ms(job_started),
        )

    def _on_done(self, future: Future) -> None:
        self._running_job_id = None
        try:
            result = future.result()
        except DuplicateSnapshotError as exc:
            self._discard(f"duplicate_snapshot:{exc.snapshot_hash}")
            append_diagnostics_log("capture_pipeline", f"discarded duplicate_snapshot={exc.snapshot_hash}")
            return
        except Exception as exc:
            self._discard(f"pipeline_failed:{exc}")
            append_diagnostics_log("capture_pipeline", f"failed error={exc}")
            return
        if result.job_id != self._latest_job_id:
            self._discard(f"stale_result:{result.job_id}")
            append_diagnostics_log("capture_pipeline", f"discarded stale_result={result.job_id}")
            return
        self.last_result = result
        self._record_capture_sample(result)
        self._set_status(f"pipeline_finished: job={result.job_id}, page={result.page.page_type.value}, messages={len(result.messages)}")
        append_diagnostics_log(
            "capture_pipeline",
            f"finished job={result.job_id} page={result.page.page_type.value} messages={len(result.messages)} "
            f"title_ms={result.title_ocr_elapsed_ms if result.title_ocr_elapsed_ms is not None else '-'} "
            f"content_ms={result.content_ocr_elapsed_ms if result.content_ocr_elapsed_ms is not None else '-'} "
            f"total_ms={result.total_elapsed_ms if result.total_elapsed_ms is not None else '-'} "
            f"warning={result.ocr_result.warning or '-'}",
        )
        self.result_ready.emit(result)

    def _record_capture_sample(self, result: PipelineResult) -> None:
        if self.capture_samples is None:
            return
        try:
            self.capture_samples.append(
                job_id=result.job_id,
                hwnd=result.hwnd,
                target_app=result.target_app,
                app_label=result.app_label,
                snapshot_hash=result.snapshot_hash,
                image_path=str(result.image_path),
                ocr_image_path=str(result.ocr_image_path),
                crop_rect_json=json.dumps(result.crop_rect.as_tuple() if result.crop_rect else None, separators=(",", ":")),
                title_ocr_image_path=str(result.title_ocr_image_path) if result.title_ocr_image_path else "",
                title_crop_rect_json=json.dumps(result.title_crop_rect.as_tuple() if result.title_crop_rect else None, separators=(",", ":")),
                title_ocr_elapsed_ms=result.title_ocr_elapsed_ms,
                content_ocr_elapsed_ms=result.content_ocr_elapsed_ms,
                total_elapsed_ms=result.total_elapsed_ms,
                ocr_engine=result.ocr_result.engine,
                ocr_warning=result.ocr_result.warning or "",
                page_type=result.page.page_type.value,
                page_confidence=result.page.confidence,
                message_count=len(result.messages),
                retained_image=self.retain_capture_images,
            )
        except Exception as exc:
            append_diagnostics_log("capture_pipeline", f"capture_sample_record_failed job={result.job_id} error={exc}")

    def _discard(self, reason: str) -> None:
        self.last_discard_reason = reason
        self.result_discarded.emit(reason)

    def _set_status(self, status: str) -> None:
        self.last_status = status
        self.status_changed.emit(status)


class DuplicateSnapshotError(RuntimeError):
    def __init__(self, snapshot_hash: str) -> None:
        super().__init__(snapshot_hash)
        self.snapshot_hash = snapshot_hash


def _heavy_ocr_min_interval_ms() -> int:
    try:
        return max(8000, int(os.environ.get("WHOCHAT_HEAVY_OCR_MIN_INTERVAL_MS", "30000")))
    except ValueError:
        return 30000


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _prepare_ocr_input(image_path: Path, layout: LayoutRegions) -> tuple[Path, LayoutRegions, tuple[int, int], Rect | None]:
    if os.environ.get("WHOCHAT_OCR_CROP_CONTENT", "1") == "0":
        return image_path, _layout_relative_to_image(layout, layout.window_rect.left, layout.window_rect.top), (
            layout.window_rect.left,
            layout.window_rect.top,
        ), None
    crop_rect = _clip_rect(Rect(layout.content_rect.left, layout.title_rect.bottom, layout.content_rect.right, layout.content_rect.bottom), layout.window_rect)
    if crop_rect.width < 120 or crop_rect.height < 160:
        return image_path, _layout_relative_to_image(layout, layout.window_rect.left, layout.window_rect.top), (
            layout.window_rect.left,
            layout.window_rect.top,
        ), None
    relative_crop = (
        crop_rect.left - layout.window_rect.left,
        crop_rect.top - layout.window_rect.top,
        crop_rect.right - layout.window_rect.left,
        crop_rect.bottom - layout.window_rect.top,
    )
    crop_path = image_path.with_name(f"{image_path.stem}_content{image_path.suffix}")
    with Image.open(image_path) as image:
        image.crop(relative_crop).save(crop_path)
    crop_layout = _layout_relative_to_image(layout, crop_rect.left, crop_rect.top)
    append_diagnostics_log(
        "capture_pipeline",
        f"ocr_crop source={image_path.name} crop={crop_rect.as_tuple()} size={crop_rect.width}x{crop_rect.height}",
    )
    return crop_path, crop_layout, (crop_rect.left, crop_rect.top), crop_rect


def _prepare_title_ocr_input(image_path: Path, layout: LayoutRegions) -> tuple[Path, LayoutRegions, tuple[int, int], Rect | None]:
    if os.environ.get("WHOCHAT_OCR_CROP_CONTENT", "1") == "0":
        return image_path, _layout_relative_to_image(layout, layout.window_rect.left, layout.window_rect.top), (
            layout.window_rect.left,
            layout.window_rect.top,
        ), None
    crop_rect = _clip_rect(layout.title_rect.inset(left=0, top=0, right=0, bottom=0), layout.window_rect)
    if crop_rect.width < 120 or crop_rect.height < 28:
        return image_path, _layout_relative_to_image(layout, layout.window_rect.left, layout.window_rect.top), (
            layout.window_rect.left,
            layout.window_rect.top,
        ), None
    relative_crop = (
        crop_rect.left - layout.window_rect.left,
        crop_rect.top - layout.window_rect.top,
        crop_rect.right - layout.window_rect.left,
        crop_rect.bottom - layout.window_rect.top,
    )
    crop_path = image_path.with_name(f"{image_path.stem}_title{image_path.suffix}")
    with Image.open(image_path) as image:
        image.crop(relative_crop).save(crop_path)
    crop_layout = _layout_relative_to_image(layout, crop_rect.left, crop_rect.top)
    append_diagnostics_log(
        "capture_pipeline",
        f"ocr_title_crop source={image_path.name} crop={crop_rect.as_tuple()} size={crop_rect.width}x{crop_rect.height}",
    )
    return crop_path, crop_layout, (crop_rect.left, crop_rect.top), crop_rect


def _merge_ocr_results(title: OcrResult, content: OcrResult) -> OcrResult:
    warnings = [value for value in [title.warning, content.warning] if value]
    boxes = _dedupe_ocr_boxes([*title.boxes, *content.boxes])
    return OcrResult(
        boxes=boxes,
        source_image=content.source_image,
        engine=content.engine if content.engine == title.engine else f"{title.engine}+{content.engine}",
        warning="; ".join(warnings) if warnings else None,
    )


def _dedupe_ocr_boxes(boxes: list[OcrTextBox]) -> list[OcrTextBox]:
    result: list[OcrTextBox] = []
    seen: set[tuple[str, tuple[int, int, int, int], int]] = set()
    for box in boxes:
        key = (" ".join(box.text.split()), box.rect.as_tuple(), round(box.confidence * 100))
        if key in seen:
            continue
        seen.add(key)
        result.append(box)
    return result


def _layout_relative_to_image(layout: LayoutRegions, origin_left: int, origin_top: int) -> LayoutRegions:
    return LayoutRegions(
        window_rect=_shift_rect(layout.window_rect, -origin_left, -origin_top),
        nav_rect=_shift_rect(layout.nav_rect, -origin_left, -origin_top),
        chat_list_rect=_shift_rect(layout.chat_list_rect, -origin_left, -origin_top),
        content_rect=_shift_rect(layout.content_rect, -origin_left, -origin_top),
        title_rect=_shift_rect(layout.title_rect, -origin_left, -origin_top),
        message_rect=_shift_rect(layout.message_rect, -origin_left, -origin_top),
        input_rect=_shift_rect(layout.input_rect, -origin_left, -origin_top),
        confidence=layout.confidence,
        source=layout.source,
        reason=layout.reason,
    )


def _offset_ocr_result(result: OcrResult, offset: tuple[int, int]) -> OcrResult:
    left, top = offset
    if left == 0 and top == 0:
        return result
    return OcrResult(
        boxes=[
            OcrTextBox(
                text=box.text,
                rect=_shift_rect(box.rect, left, top),
                confidence=box.confidence,
                region=box.region,
                source=box.source,
            )
            for box in result.boxes
        ],
        source_image=result.source_image,
        engine=result.engine,
        warning=result.warning,
    )


def _clip_rect(rect: Rect, bounds: Rect) -> Rect:
    return Rect(
        max(rect.left, bounds.left),
        max(rect.top, bounds.top),
        min(rect.right, bounds.right),
        min(rect.bottom, bounds.bottom),
    )


def _shift_rect(rect: Rect, left: int, top: int) -> Rect:
    return Rect(rect.left + left, rect.top + top, rect.right + left, rect.bottom + top)
