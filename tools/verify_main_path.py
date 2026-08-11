from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "main_path_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from whochat.app import create_app
from whochat.core.models import ContactStatus
from whochat.core.runtime import LayoutRegions, Rect
from whochat.ocr.engine import OcrEngine
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


class MainPathOcr(OcrEngine):
    name = "main-path-ocr"

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        return OcrResult(
            boxes=[
                OcrTextBox("主路径联系人", _inside(layout.title_rect, 0.05, 0.20, 0.30, 0.72), 0.92, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("今天下午能给我一个确认吗？", _inside(layout.message_rect, 0.08, 0.16, 0.46, 0.26), 0.91, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("可以，我核对后尽快回复你。", _inside(layout.message_rect, 0.56, 0.36, 0.94, 0.47), 0.90, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("输入", _inside(layout.input_rect, 0.05, 0.20, 0.18, 0.38), 0.82, OcrRegion.UNKNOWN, self.name),
            ],
            source_image=str(image_path),
            engine=self.name,
        )


def main() -> int:
    app = create_app()
    services = build_services()
    services.pipeline.ocr_engine = MainPathOcr()
    services.pipeline.capture_func = _capture

    window = MainWindow(services)
    window._config.ai.provider = "Local Preview"
    window._config.ai.api_key = ""
    floating = FloatingWidget()
    window.attach_floating_widget(floating)

    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=901, title="微信", process_name="Weixin", rect=(80, 60, 1280, 860), visible=True)
    )
    if state.layout is None or not state.capture_decision.should_capture:
        raise RuntimeError(f"runtime should be capturable: {state}")

    result = services.pipeline.run_sync(state)
    if result is None:
        raise RuntimeError("pipeline did not return result")
    _wait_for(
        app,
        lambda: services.ingestion.last_result is not None and services.ingestion.last_result.accepted
        and services.ingestion.last_result.inserted_messages >= 2,
        "full ingestion result",
    )
    ingestion = services.ingestion.last_result
    if ingestion is None or not ingestion.accepted or ingestion.contact is None:
        raise RuntimeError(f"ingestion should accept captured chat: {ingestion}")
    if ingestion.contact.display_name != "主路径联系人":
        raise RuntimeError(f"contact title mismatch: {ingestion.contact}")
    stored = services.messages.list_for_contact(ingestion.contact.id)
    if len(stored) != 2:
        raise RuntimeError(f"expected two stored messages, got {len(stored)}")

    blocked = services.reply_generator.generate(window._build_reply_context(), window._config)
    if blocked.allowed or "联系人尚未确认" not in blocked.status:
        raise RuntimeError(f"unconfirmed contact should block AI suggestions: {blocked}")

    confirmed = services.contacts.update_profile(ingestion.contact.id, status=ContactStatus.CONFIRMED)
    window._reload_contact_list(confirmed.id)
    window._render_contact_detail(confirmed)
    window._refresh_overview_data()
    window._refresh_reply_suggestions()
    _wait_for(app, lambda: services.reply_tasks.last_result is not None, "reply task")
    task = services.reply_tasks.last_result
    if task is None or not task.result.allowed or len(task.result.suggestions) < 1:
        raise RuntimeError(f"reply task should generate suggestions: {task}")
    _wait_for(app, lambda: floating.suggestion_buttons[0].isEnabled(), "floating suggestion button")
    first = floating.suggestion_buttons[0]
    copied_text = str(first.property("reply_text") or "")
    if not copied_text:
        raise RuntimeError("floating suggestion has no reply text")
    QTest.mouseClick(first, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first.rect().center())
    copied = QApplication.clipboard().text()
    if copied != copied_text:
        raise RuntimeError(f"clipboard mismatch: {copied!r} != {copied_text!r}")

    audits = services.generation_logs.tail(5)
    samples = services.capture_samples.tail(5)
    if not audits or not samples:
        raise RuntimeError("main path should write generation audit and capture sample metadata")

    print(
        f"contact={confirmed.display_name} messages={len(stored)} "
        f"suggestions={len(task.result.suggestions)} copied={copied[:24]} "
        f"capture_samples={len(samples)} audits={len(audits)}"
    )
    window.close()
    floating.close()
    app.quit()
    return 0


def _wait_for(app, predicate, label: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise RuntimeError(f"timed out waiting for {label}")


def _capture(_rect, output: Path) -> Path:
    image = Image.new("RGB", (1200, 800), "#f7f8fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 76, 800), fill="#1f2937")
    draw.rectangle((76, 0, 386, 800), fill="#ffffff")
    draw.rectangle((386, 0, 1200, 74), fill="#ffffff")
    draw.rectangle((386, 74, 1200, 650), fill="#eef2f7")
    draw.rectangle((386, 650, 1200, 800), fill="#ffffff")
    draw.rounded_rectangle((452, 140, 760, 196), radius=8, fill="#ffffff", outline="#d9e2ec")
    draw.rounded_rectangle((794, 258, 1134, 316), radius=8, fill="#d7f5e8", outline="#b7e4d1")
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
