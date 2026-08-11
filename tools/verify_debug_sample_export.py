from __future__ import annotations

import os
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "debug_sample_export_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.config import AppConfig
from whochat.core.runtime import LayoutRegions, Rect
from whochat.ocr.engine import OcrEngine
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow
from tools.export_screenshot_sample import export_sample_from_debug_sample
from tools.verify_screenshot_samples import _verify_manifest


class DebugExportOcr(OcrEngine):
    name = "debug-export-ocr"

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        return OcrResult(
            boxes=[
                OcrTextBox("调试样本联系人", _inside(layout.title_rect, 0.05, 0.20, 0.32, 0.70), 0.92, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("请帮我确认一下。", _inside(layout.message_rect, 0.08, 0.18, 0.38, 0.28), 0.90, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("我确认后回复你。", _inside(layout.message_rect, 0.58, 0.38, 0.92, 0.49), 0.89, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("输入", _inside(layout.input_rect, 0.05, 0.20, 0.18, 0.38), 0.82, OcrRegion.UNKNOWN, self.name),
            ],
            source_image=str(image_path),
            engine=self.name,
        )


def main() -> int:
    app = create_app()
    services = build_services()
    services.pipeline.ocr_engine = DebugExportOcr()
    services.pipeline.capture_func = _capture
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=1001, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    if state.layout is None:
        raise RuntimeError("expected layout")
    result = services.pipeline.run_sync(state)
    if result is None or len(result.messages) != 2:
        raise RuntimeError(f"expected parsed pipeline result: {result}")

    window = MainWindow(services)
    window._config.privacy.save_debug_screenshots = True
    window._copy_diagnostics_bundle()
    from PySide6.QtWidgets import QApplication

    clipboard = QApplication.clipboard().text()
    if "title_ocr=job:" not in clipboard or "elapsed_ms:" not in clipboard or "调试样本联系人" not in clipboard:
        raise RuntimeError(f"diagnostics bundle should include title OCR summary: {clipboard}")
    if "# capture_samples" not in clipboard or "capture_perf=status:" not in clipboard or "title_ms=" not in clipboard or "content_ms=" not in clipboard:
        raise RuntimeError(f"diagnostics bundle should include capture performance summary: {clipboard}")
    window._save_debug_sample()
    sample_dirs = sorted((DATA_DIR / "debug_samples").glob("sample-*"))
    if not sample_dirs:
        raise RuntimeError("debug sample was not saved")
    exported = export_sample_from_debug_sample(
        sample_dirs[-1],
        name="debug_export_sample",
        output_root=DATA_DIR / "screenshot_samples",
    )
    diagnostics = json.loads((sample_dirs[-1] / "diagnostics.json").read_text(encoding="utf-8"))
    pipeline = diagnostics.get("pipeline", {})
    if pipeline.get("last_result_target_app") != "wechat" or pipeline.get("last_result_app_label") != "微信":
        raise RuntimeError(f"debug sample should include target app context: {pipeline}")
    if pipeline.get("last_title_target_app") != "wechat" or pipeline.get("last_title_app_label") != "微信":
        raise RuntimeError(f"debug sample should include title target app context: {pipeline}")
    if not pipeline.get("last_title_crop_rect") or not pipeline.get("last_title_ocr_boxes"):
        raise RuntimeError(f"debug sample should include title OCR diagnostics: {pipeline}")
    if pipeline.get("last_title_elapsed_ms") is None or pipeline.get("last_result_content_elapsed_ms") is None:
        raise RuntimeError(f"debug sample should include OCR elapsed timing: {pipeline}")
    title_image = pipeline.get("last_title_image")
    if title_image and not (sample_dirs[-1] / Path(title_image).name).exists():
        raise RuntimeError(f"debug sample should copy title crop image: {title_image}")
    manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    source = manifest.get("source", {})
    if source.get("target_app") != "wechat" or source.get("app_label") != "微信":
        raise RuntimeError(f"exported manifest should include target app context: {source}")
    _verify_manifest(exported / "manifest.json", "structured", "ch", 0.5, False)
    print(f"debug_sample={sample_dirs[-1]} exported={exported}")
    window.close()
    app.quit()
    return 0


def _capture(_rect, output: Path) -> Path:
    image = Image.new("RGB", (1200, 800), "#f7f8fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 76, 800), fill="#1f2937")
    draw.rectangle((76, 0, 386, 800), fill="#ffffff")
    draw.rectangle((386, 0, 1200, 74), fill="#ffffff")
    draw.rectangle((386, 74, 1200, 650), fill="#eef2f7")
    draw.rectangle((386, 650, 1200, 800), fill="#ffffff")
    draw.rounded_rectangle((452, 150, 760, 205), radius=8, fill="#ffffff", outline="#d9e2ec")
    draw.rounded_rectangle((842, 270, 1150, 326), radius=8, fill="#d7f5e8", outline="#b7e4d1")
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
