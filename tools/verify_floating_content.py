from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "floating_content_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QPushButton

from whochat.ai.models import ReplyGenerationResult, ReplySuggestion
from whochat.app import create_app
from whochat.core.models import ContactStatus
from whochat.core.runtime import CaptureDecision, PageClassification, PageType
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("悬浮验证对象")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    strategy = services.strategies.get(contact.strategy_id)

    window = MainWindow(services)
    floating = FloatingWidget()
    window.attach_floating_widget(floating)
    services.runtime.update_from_window_info(
        WindowInfo(hwnd=991, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    window._set_active_capture_contact(contact, 991)
    services.runtime._state = replace(
        services.runtime.state,
        page=PageClassification(PageType.UNKNOWN, 0.0, "区域不可用，需校准"),
        capture_decision=CaptureDecision(False, "区域不可用，需校准"),
    )
    window._sync_floating_content(contact=contact, strategy=strategy)
    if floating.contact_label.text() != "微信·悬浮验证对象（默认）":
        raise RuntimeError(f"floating contact mismatch: {floating.contact_label.text()}")
    if floating.group_label.text() != (strategy.name if strategy else "默认"):
        raise RuntimeError(f"floating group mismatch: {floating.group_label.text()}")
    if "聊天页" not in floating.status_label.toolTip() and "生成" not in floating.status_label.toolTip():
        raise RuntimeError(f"floating status tooltip should carry action guidance: {floating.status_label.toolTip()}")
    if floating.action_button.isHidden():
        raise RuntimeError("floating should show direct calibration action when page is blocked")
    if floating.action_button.toolTip() != "打开区域校准":
        raise RuntimeError("floating calibration action has an unclear tooltip")

    services.runtime._state = replace(services.runtime.state, page=PageClassification(PageType.CHAT_DM, 0.9, "verify chat"))
    services.runtime.apply_title_result(SimpleNamespace(hwnd=991, snapshot_hash="title-fast-path"))
    if floating.status_label.text() != "OCR:读取消息":
        raise RuntimeError(f"floating should show title fast path OCR status: {floating.status_label.text()}")

    blocked = ReplyGenerationResult(False, "blocked:unknown_page", [], "Local Preview")
    floating.update_reply_result(blocked)
    buttons = [button for button in floating.findChildren(QPushButton) if button.objectName() == "FloatingSuggestionButton"]
    if any(button.isEnabled() for button in buttons):
        raise RuntimeError("blocked floating suggestions should be disabled")

    allowed = ReplyGenerationResult(
        True,
        "local_preview",
        [
            ReplySuggestion("稳妥", "这是第一条真实建议，需要完整保留。\n第二行不应撑高按钮。", "low", "verify"),
            ReplySuggestion("边界", "这是第二条真实建议", "medium", "verify"),
        ],
        "Local Preview",
    )
    floating.update_reply_result(allowed)
    if floating.status_label.text() != "中风险":
        raise RuntimeError(f"floating risk status mismatch: {floating.status_label.text()}")
    first = buttons[0]
    if first.text() != "这是第一条真实建..." or first.toolTip() != "这是第一条真实建议，需要完整保留。\n第二行不应撑高按钮。":
        raise RuntimeError(f"floating suggestion button mismatch: {first.text()} / {first.toolTip()}")
    floating._copy(str(first.property("reply_text") or ""))
    copied = QApplication.clipboard().text()
    if copied != "这是第一条真实建议，需要完整保留。\n第二行不应撑高按钮。":
        raise RuntimeError(f"floating copied wrong text: {copied}")

    print(f"contact={floating.contact_label.text()} group={floating.group_label.text()} copied={copied}")
    window.close()
    floating.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
