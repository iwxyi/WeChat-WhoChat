from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "pipeline_ocr_crop_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.core.models import Speaker
from whochat.core.runtime import LayoutRegions, PageType, Rect
from whochat.ocr.engine import OcrEngine
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.pipeline import CapturePipelineService


class RecordingOcrEngine(OcrEngine):
    name = "recording-ocr"

    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[int, int], LayoutRegions]] = []

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        with Image.open(image_path) as image:
            image_size = image.size
        self.calls.append((image_path, image_size, layout))
        return OcrResult(
            boxes=[
                OcrTextBox("裁剪联系人", _inside(layout.title_rect, 0.05, 0.20, 0.25, 0.70), 0.90, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("这个窗口不是从零坐标开始", _inside(layout.message_rect, 0.08, 0.18, 0.48, 0.28), 0.88, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("坐标映射后仍然可解析。", _inside(layout.message_rect, 0.56, 0.38, 0.94, 0.49), 0.87, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("输入", _inside(layout.input_rect, 0.05, 0.20, 0.18, 0.38), 0.80, OcrRegion.UNKNOWN, self.name),
            ],
            source_image=str(image_path),
            engine=self.name,
        )


def main() -> int:
    services = build_services()
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=701, title="微信", process_name="Weixin", rect=(120, 80, 1320, 880), visible=True)
    )
    if state.layout is None:
        raise RuntimeError("expected layout")
    engine = RecordingOcrEngine()
    pipeline = CapturePipelineService(ocr_engine=engine, capture_func=_capture)
    result = pipeline.run_sync(state)
    if result is None:
        raise RuntimeError("pipeline did not return result")
    if pipeline.last_title_result is None:
        raise RuntimeError("pipeline should expose last_title_result")
    if pipeline.last_title_result.title_crop_rect is None or pipeline.last_title_result.title_ocr_image_path is None:
        raise RuntimeError(f"title result should include title crop metadata: {pipeline.last_title_result}")
    if len(engine.calls) != 2:
        raise RuntimeError(f"expected title and content OCR calls, got {len(engine.calls)}")
    title_call, content_call = engine.calls
    if title_call[1][1] >= content_call[1][1]:
        raise RuntimeError(f"title crop should be shorter than content crop, got {title_call[1]} and {content_call[1]}")
    if content_call[1][0] >= state.layout.window_rect.width:
        raise RuntimeError(f"expected OCR crop smaller than full window, got {content_call[1]}")
    if content_call[2].content_rect.left != 0:
        raise RuntimeError(f"expected cropped layout content origin, got {content_call[2]}")
    if result.title_ocr_image_path is None or result.title_crop_rect is None:
        raise RuntimeError("pipeline result should expose title OCR crop metadata")
    if result.title_ocr_elapsed_ms is None or result.content_ocr_elapsed_ms is None or result.total_elapsed_ms is None:
        raise RuntimeError(f"pipeline result should expose OCR timings: {result}")
    if pipeline.last_title_result is None or pipeline.last_title_result.elapsed_ms is None:
        raise RuntimeError(f"title result should expose elapsed timing: {pipeline.last_title_result}")
    if result.page.page_type != PageType.CHAT_DM or len(result.messages) != 2:
        raise RuntimeError(f"cropped OCR did not parse chat messages: page={result.page} messages={result.messages}")
    if result.messages[0].speaker != Speaker.OTHER or result.messages[1].speaker != Speaker.ME:
        raise RuntimeError(f"speaker mapping failed after coordinate offset: {result.messages}")
    if min(box.rect.left for box in result.ocr_result.boxes) < state.layout.content_rect.left:
        raise RuntimeError("OCR boxes were not offset back to absolute content coordinates")

    print(
        f"full={state.layout.window_rect.width}x{state.layout.window_rect.height} "
        f"title_crop={title_call[1]} content_crop={content_call[1]} messages={len(result.messages)}"
    )
    return 0


def _capture(_rect, output: Path) -> Path:
    image = Image.new("RGB", (1200, 800), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 78, 800), fill="#1f2937")
    draw.rectangle((78, 0, 380, 800), fill="#ffffff")
    draw.rectangle((380, 0, 1200, 80), fill="#ffffff")
    draw.rectangle((380, 80, 1200, 650), fill="#eef2f7")
    draw.rectangle((380, 650, 1200, 800), fill="#ffffff")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def _inside(rect: Rect, left: float, top: float, right: float, bottom: float) -> Rect:
    return Rect(
        rect.left + round(rect.width * left),
        rect.top + round(rect.height * top),
        rect.left + round(rect.width * right),
        rect.top + round(rect.height * bottom),
    )


if __name__ == "__main__":
    raise SystemExit(main())
