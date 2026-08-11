from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "title_fast_path_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.core.models import ContactStatus
from whochat.core.runtime import LayoutRegions, Rect
from whochat.ocr.engine import OcrEngine
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services


class SplitOcr(OcrEngine):
    name = "split-ocr"

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        if image_path.stem.endswith("_title"):
            return OcrResult(
                boxes=[
                    OcrTextBox("□", _inside(layout.title_rect, 0.72, 0.18, 0.76, 0.58), 0.96, OcrRegion.UNKNOWN, self.name),
                    OcrTextBox("标题快路径群（18）", _inside(layout.title_rect, 0.05, 0.20, 0.34, 0.72), 0.92, OcrRegion.UNKNOWN, self.name),
                ],
                source_image=str(image_path),
                engine=self.name,
            )
        return OcrResult(
            boxes=[
                OcrTextBox("收到这个需求了吗？", _inside(layout.message_rect, 0.08, 0.18, 0.44, 0.28), 0.88, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("收到了，我整理后回复。", _inside(layout.message_rect, 0.56, 0.38, 0.94, 0.49), 0.87, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("输入", _inside(layout.input_rect, 0.05, 0.20, 0.18, 0.38), 0.80, OcrRegion.UNKNOWN, self.name),
            ],
            source_image=str(image_path),
            engine=self.name,
        )


def main() -> int:
    services = build_services()
    services.pipeline.ocr_engine = SplitOcr()
    services.pipeline.capture_func = _capture
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=771, title="微信", process_name="Weixin", rect=(80, 60, 1280, 860), visible=True)
    )
    result = services.pipeline.run_sync(state)
    if result is None:
        raise RuntimeError("pipeline did not return result")
    if services.pipeline.last_title_result is None:
        raise RuntimeError("pipeline did not expose title result")
    title_state = services.runtime.apply_title_result(services.pipeline.last_title_result)
    if title_state.pipeline_status != "title_ready" or not title_state.ocr_pending:
        raise RuntimeError(f"title result should update runtime status: {title_state}")
    title_ingestion = services.ingestion.ingest_title_result(services.pipeline.last_title_result)
    if not title_ingestion.accepted or title_ingestion.contact is None:
        raise RuntimeError(f"title ingestion should accept contact: {title_ingestion}")
    if title_ingestion.contact.display_name != "标题快路径群（18）":
        raise RuntimeError(f"title filter selected wrong contact: {title_ingestion.contact}")
    if title_ingestion.contact.status != ContactStatus.SUSPECTED:
        raise RuntimeError(f"title contact should be suspected: {title_ingestion.contact.status}")
    full = services.ingestion.ingest_pipeline_result(result)
    if full is None or not full.accepted or full.inserted_messages != 2:
        raise RuntimeError(f"full ingestion should store messages after title path: {full}")
    print(
        f"title_contact={title_ingestion.contact.display_name} "
        f"full_inserted={full.inserted_messages} messages={len(result.messages)}"
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
