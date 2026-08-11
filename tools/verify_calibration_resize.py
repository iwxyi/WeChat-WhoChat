from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from whochat.platform.adapters import WeChatAdapter
from whochat.platform.window_tracker import WindowInfo
from whochat.ui.calibration_overlay import CalibrationCanvas


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    adapter = WeChatAdapter()
    snapshot = adapter.window_snapshot(WindowInfo(hwnd=1, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True))
    layout = adapter.estimate_layout(snapshot)
    if layout is None:
        raise RuntimeError("layout missing")
    canvas = CalibrationCanvas(layout)
    canvas.resize(900, 520)
    canvas.show()
    app.processEvents()

    before = canvas.layout_regions.message_rect
    visual = canvas._to_canvas_rect(before, canvas._canvas_rect())
    start = QPoint(visual.left(), visual.center().y())
    end = start + QPoint(-24, 0)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    after = canvas.layout_regions.message_rect
    if after.width == before.width and after.height == before.height:
        raise RuntimeError(f"dragging calibration edge/corner should resize region: before={before} after={after}")

    canvas.close()
    app.quit()
    print(f"resized_message={before.as_tuple()}->{after.as_tuple()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
