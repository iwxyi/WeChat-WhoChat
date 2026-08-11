from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["WHOCHAT_DATA_DIR"] = str(ROOT / "tmp" / "calibration_ui" / "data")
os.environ["WHOCHAT_DB_PATH"] = str(ROOT / "tmp" / "calibration_ui" / "data" / "whochat.db")

from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from whochat.app import create_app
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import CalibrationDialog, MainWindow


def main() -> int:
    out = ROOT / "tmp" / "calibration_ui"
    out.mkdir(parents=True, exist_ok=True)
    screenshot = out / "synthetic_wechat.png"
    _write_synthetic_screenshot(screenshot)

    app = create_app()
    services = build_services()
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=300, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    if state.layout is None:
        raise RuntimeError("layout missing")
    main = MainWindow(services)
    dialog = CalibrationDialog(main, state.layout, screenshot)
    dialog.show()
    app.processEvents()

    before = dialog.canvas.layout_regions.message_rect.as_tuple()
    canvas_rect = dialog.canvas._canvas_rect()
    start = canvas_rect.center()
    QTest.mousePress(dialog.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(dialog.canvas, start + QPoint(30, 18))
    QTest.mouseRelease(dialog.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(30, 18))
    app.processEvents()
    after = dialog.canvas.layout_regions.message_rect.as_tuple()
    if before == after:
        raise RuntimeError("dragging calibration region did not update layout")
    if "engine=preview-fixture" not in dialog.preview.toPlainText():
        raise RuntimeError("OCR preview summary was not rendered")
    if not dialog.canvas._ocr_result or not dialog.canvas._ocr_result.boxes:
        raise RuntimeError("OCR preview boxes were not attached to canvas")

    pixmap = dialog.grab()
    output = out / "calibration_dialog.png"
    if pixmap.isNull() or not pixmap.save(str(output)):
        raise RuntimeError("failed to save calibration dialog screenshot")

    values = dialog.values()
    calibration = services.calibrations.create_from_layout(
        name=values["name"],
        target=state.window.target,
        window_rect=state.window.rect,
        layout=values["layout"],
        theme=values["theme"],
        active=True,
    )
    if services.calibrations.get_active(state.window.target).id != calibration.id:
        raise RuntimeError("calibration from overlay was not persisted")

    print(f"dialog={output}")
    print(f"before={before}")
    print(f"after={after}")
    print(f"calibration={calibration.id}")
    dialog.close()
    main.close()
    return 0


def _write_synthetic_screenshot(path: Path) -> None:
    image = Image.new("RGB", (1200, 800), "#f6f7f9")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 72, 800), fill="#1f2933")
    draw.rectangle((72, 0, 390, 800), fill="#ffffff")
    draw.rectangle((390, 0, 1200, 64), fill="#ffffff")
    draw.rectangle((390, 64, 1200, 650), fill="#edf2f7")
    draw.rectangle((390, 650, 1200, 800), fill="#ffffff")
    draw.rounded_rectangle((458, 140, 760, 190), radius=8, fill="#ffffff", outline="#d9e2ec")
    draw.rounded_rectangle((800, 230, 1130, 282), radius=8, fill="#d7f5e8", outline="#b7e4d1")
    draw.text((95, 42), "联系人 A", fill="#102a43")
    draw.text((420, 23), "联系人 A", fill="#102a43")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


if __name__ == "__main__":
    raise SystemExit(main())
