from __future__ import annotations

import os
import sys
from concurrent.futures import Future
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["WHOCHAT_DATA_DIR"] = str(ROOT / "tmp" / "pipeline_backpressure_verify" / "data")
os.environ["WHOCHAT_DB_PATH"] = str(ROOT / "tmp" / "pipeline_backpressure_verify" / "data" / "whochat.db")

from whochat.core.runtime import (
    CaptureDecision,
    LayoutRegions,
    PageClassification,
    PageType,
    Rect,
    RegionSource,
    RuntimeState,
    TargetApp,
    WindowSnapshot,
    WindowState,
)
from whochat.ocr.engine import PreviewOcrEngine
from whochat.ocr.models import OcrResult
from whochat.services.pipeline import CapturePipelineService, PipelineResult


class PaddleLikeEngine(PreviewOcrEngine):
    name = "paddleocr"


class HoldingExecutor:
    def __init__(self) -> None:
        self.submitted = 0
        self.future = Future()

    def submit(self, fn, *args, **kwargs):
        self.submitted += 1
        return self.future


def main() -> int:
    state = _state()
    executor = HoldingExecutor()
    pipeline = CapturePipelineService(ocr_engine=PaddleLikeEngine(), capture_func=_capture, executor=executor)
    first = pipeline.submit(state)
    second = pipeline.submit(state)
    if first != 1:
        raise RuntimeError(f"expected first job id 1, got {first}")
    if second is not None:
        raise RuntimeError(f"busy pipeline should reject second job, got {second}")
    if executor.submitted != 1:
        raise RuntimeError(f"busy pipeline queued extra work: {executor.submitted}")
    if not str(pipeline.last_discard_reason).startswith("pipeline_busy"):
        raise RuntimeError(f"expected busy discard, got {pipeline.last_discard_reason}")

    result = PipelineResult(
        job_id=1,
        hwnd=1,
        target_app="wechat",
        app_label="微信",
        snapshot_hash="hash",
        image_path=Path("capture.png"),
        ocr_image_path=Path("capture_content.png"),
        crop_rect=None,
        layout=state.layout,
        ocr_result=OcrResult([], "capture.png", "paddleocr", None),
        page=PageClassification(PageType.UNKNOWN, 0.0, "verify"),
        messages=[],
        created_at="2026-08-04T00:00:00+00:00",
    )
    executor.future.set_result(result)
    cooled = pipeline.submit(state)
    if cooled is not None:
        raise RuntimeError(f"paddle cooldown should reject immediate submit, got {cooled}")
    if not str(pipeline.last_discard_reason).startswith("pipeline_cooldown"):
        raise RuntimeError(f"expected cooldown discard, got {pipeline.last_discard_reason}")
    print(f"submitted={executor.submitted} busy={pipeline.last_discard_reason}")
    return 0


def _state() -> RuntimeState:
    window = WindowSnapshot(
        target=TargetApp.WECHAT,
        hwnd=1,
        title="WeChat",
        process_name="WeChat.exe",
        rect=Rect(0, 0, 1000, 800),
        state=WindowState.VISIBLE,
    )
    layout = LayoutRegions(
        window_rect=Rect(0, 0, 1000, 800),
        nav_rect=Rect(0, 0, 70, 800),
        chat_list_rect=Rect(70, 0, 320, 800),
        content_rect=Rect(320, 0, 1000, 800),
        title_rect=Rect(320, 0, 1000, 80),
        message_rect=Rect(320, 80, 1000, 650),
        input_rect=Rect(320, 650, 1000, 800),
        confidence=0.9,
        source=RegionSource.AUTO,
        reason="verify",
    )
    page = PageClassification(PageType.CHAT_DM, 0.9, "verify")
    return RuntimeState(window=window, layout=layout, page=page, capture_decision=CaptureDecision(True, "verify"), paused=False)


def _capture(_rect, output: Path) -> Path:
    return output


if __name__ == "__main__":
    raise SystemExit(main())
