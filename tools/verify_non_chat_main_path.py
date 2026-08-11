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

DATA_DIR = ROOT / "tmp" / "non_chat_main_path_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QPushButton

from whochat.app import create_app
from whochat.core.models import ContactStatus
from whochat.core.runtime import LayoutRegions, Rect
from whochat.ocr.engine import OcrEngine
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


class SwitchingOcr(OcrEngine):
    name = "non-chat-main-path-ocr"

    def __init__(self) -> None:
        self.mode = "chat"

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        if self.mode == "settings":
            boxes = [
                OcrTextBox("设置", _inside(layout.title_rect, 0.05, 0.20, 0.16, 0.72), 0.94, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("账号与安全", _inside(layout.message_rect, 0.10, 0.12, 0.32, 0.20), 0.91, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("消息通知", _inside(layout.message_rect, 0.10, 0.24, 0.30, 0.32), 0.90, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("隐私", _inside(layout.message_rect, 0.10, 0.36, 0.22, 0.44), 0.90, OcrRegion.UNKNOWN, self.name),
            ]
        else:
            boxes = [
                OcrTextBox("主路径联系人", _inside(layout.title_rect, 0.05, 0.20, 0.30, 0.72), 0.92, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("今天下午能给我一个确认吗？", _inside(layout.message_rect, 0.08, 0.16, 0.46, 0.26), 0.91, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("可以，我核对后尽快回复你。", _inside(layout.message_rect, 0.56, 0.36, 0.94, 0.47), 0.90, OcrRegion.UNKNOWN, self.name),
                OcrTextBox("输入", _inside(layout.input_rect, 0.05, 0.20, 0.18, 0.38), 0.82, OcrRegion.UNKNOWN, self.name),
            ]
        return OcrResult(boxes=boxes, source_image=str(image_path), engine=self.name)


def main() -> int:
    app = create_app()
    services = build_services()
    ocr = SwitchingOcr()
    services.pipeline.ocr_engine = ocr
    services.pipeline.capture_func = _capture

    window = MainWindow(services)
    window._config.ai.provider = "Local Preview"
    floating = FloatingWidget()
    window.attach_floating_widget(floating)

    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=902, title="微信", process_name="Weixin", rect=(80, 60, 1280, 860), visible=True)
    )
    result = services.pipeline.run_sync(state)
    if result is None:
        raise RuntimeError("chat pipeline did not return result")
    _wait_for(
        app,
        lambda: services.ingestion.last_result is not None
        and services.ingestion.last_result.accepted
        and services.ingestion.last_result.inserted_messages >= 2,
        "full chat ingestion",
    )
    contact = services.ingestion.last_result.contact if services.ingestion.last_result else None
    if contact is None:
        raise RuntimeError("chat ingestion did not resolve contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    window._reload_contact_list(contact.id)
    window._render_contact_detail(contact)
    before_count = len(services.messages.list_for_contact(contact.id))
    if before_count != 2:
        raise RuntimeError(f"expected two chat messages before non-chat page, got {before_count}")

    window._refresh_reply_suggestions()
    _wait_for(app, lambda: services.reply_tasks.last_result is not None, "initial reply task")
    buttons = _floating_buttons(floating)
    _wait_for(app, lambda: buttons[0].isEnabled(), "initial floating suggestion")

    ocr.mode = "settings"
    services.pipeline.capture_func = _capture_settings
    services.pipeline.reset_snapshot_hash_cache()
    non_chat = services.pipeline.run_sync(services.runtime.state)
    if non_chat is None:
        raise RuntimeError("settings pipeline did not return result")
    _wait_for(app, lambda: services.runtime.state.page.page_type.value == "settings", "settings runtime")
    _wait_for(app, lambda: services.ingestion.last_result is not None and services.ingestion.last_result.reason == "page_blocked:settings", "settings ingestion")
    window._refresh_overview_data()

    after_count = len(services.messages.list_for_contact(contact.id))
    if after_count != before_count:
        raise RuntimeError(f"non-chat page polluted stored messages: before={before_count} after={after_count}")
    blocked = services.reply_generator.generate(window._build_reply_context(), window._config)
    if blocked.allowed or "settings" not in blocked.status:
        raise RuntimeError(f"settings page should block replies: {blocked}")
    if any(button.isEnabled() for button in buttons):
        raise RuntimeError("floating suggestions should be disabled on settings page")

    print(f"non_chat={non_chat.page.page_type.value} messages={after_count} floating_enabled=0 status={blocked.status}")
    window.close()
    floating.close()
    app.quit()
    return 0


def _floating_buttons(floating: FloatingWidget) -> list[QPushButton]:
    return [button for button in floating.findChildren(QPushButton) if button.objectName() == "FloatingSuggestionButton"]


def _wait_for(app, predicate, label: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise RuntimeError(f"timed out waiting for {label}")


def _capture(_rect, output: Path) -> Path:
    return _write_image(output, "#f7f8fb")


def _capture_settings(_rect, output: Path) -> Path:
    return _write_image(output, "#f3f0f8")


def _write_image(output: Path, background: str) -> Path:
    image = Image.new("RGB", (1200, 800), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 76, 800), fill="#1f2937")
    draw.rectangle((76, 0, 386, 800), fill="#ffffff")
    draw.rectangle((386, 0, 1200, 74), fill="#ffffff")
    draw.rectangle((386, 74, 1200, 650), fill="#eef2f7")
    draw.rectangle((386, 650, 1200, 800), fill="#ffffff")
    if background == "#f3f0f8":
        draw.rectangle((430, 126, 1120, 184), fill="#f6eef8", outline="#d8bfd8")
        draw.rectangle((430, 214, 1120, 272), fill="#f6eef8", outline="#d8bfd8")
        draw.rectangle((430, 302, 1120, 360), fill="#f6eef8", outline="#d8bfd8")
    else:
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
