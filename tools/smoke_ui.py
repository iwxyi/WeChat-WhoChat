from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from whochat.ai.models import ReplyGenerationResult, ReplySuggestion
from whochat.app import create_app
from whochat.core.models import ContactStatus, MemoryKind, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.storage.repositories import new_id
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


def grab_widget(widget, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    if pixmap.isNull():
        raise RuntimeError(f"failed to grab {path}")
    if not pixmap.save(str(path)):
        raise RuntimeError(f"failed to save {path}")


def main() -> int:
    out = ROOT / "tmp" / "verification"
    shutil.rmtree(out, ignore_errors=True)
    os.environ["WHOCHAT_CONFIG_DIR"] = str(out / "config")
    os.environ["WHOCHAT_DATA_DIR"] = str(out / "data")
    os.environ["WHOCHAT_DB_PATH"] = str(out / "data" / "whochat.db")
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("烟测联系人")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    services.memories.add_pending(contact.id, MemoryKind.FACT, "烟测联系人偏好简短明确的回复", 0.91)
    services.messages.add_message(
        Message(
            id=new_id("message"),
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="下午前能确认吗？",
            content_type="text",
            ocr_confidence=0.98,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="smoke-message-1",
            source="smoke_ui",
        )
    )
    main_window = MainWindow(services)
    runtime_state = services.runtime.update_from_window_info(
        WindowInfo(
            hwnd=200,
            title="微信",
            process_name="Weixin",
            rect=(20, 20, 1220, 820),
            visible=True,
        )
    )
    runtime_state = replace(
        runtime_state,
        page=PageClassification(PageType.CHAT_DM, 0.78, "smoke verified chat page"),
        visible_message_count=1,
        pipeline_status="finished:chat_dm",
    )
    services.runtime._state = runtime_state
    main_window.update_runtime_state(runtime_state)
    main_window._set_active_capture_contact(contact, 200)
    main_window._sync_floating_content(contact=contact)
    floating = FloatingWidget()
    main_window.attach_floating_widget(floating)
    main_window.show()
    floating.show_waiting()
    app.processEvents()
    overview_text = main_window._overview_contact_notes.toPlainText()
    if "烟测联系人偏好简短明确的回复" not in overview_text:
        raise RuntimeError("overview contact rail did not render real memory data")
    table = main_window._overview_chat_table
    table_text = "\n".join(
        table.item(row, column).text()
        for row in range(table.rowCount())
        for column in range(table.columnCount())
        if table.item(row, column) is not None
    )
    if "尚未完成一次 OCR 采集" not in table_text:
        raise RuntimeError("overview chat table did not clearly show missing latest OCR result")
    if "示例" in table_text:
        raise RuntimeError("overview chat table still contains demo rows")
    status_table = main_window._overview_status_table
    status_stages = {
        status_table.item(row, 0).text()
        for row in range(status_table.rowCount())
        if status_table.item(row, 0) is not None
    }
    expected_stages = {"窗口", "页面", "联系人", "采集", "OCR", "隐私", "AI"}
    if status_stages != expected_stages:
        raise RuntimeError(f"overview status chain stages mismatch: {status_stages}")
    status_summary = main_window._overview_status_summary.text()
    if "窗口:" not in status_summary or "OCR:" not in status_summary or "AI:" not in status_summary:
        raise RuntimeError(f"overview status summary is incomplete: {status_summary}")
    next_action = main_window._overview_next_action.text()
    next_action_meta = main_window._overview_next_action_meta.text()
    if "下一步：" not in next_action or not next_action_meta:
        raise RuntimeError(f"overview next action did not expose primary blocker: {next_action} / {next_action_meta}")

    main_window._render_reply_suggestions(
        ReplyGenerationResult(
            True,
            "local_preview",
            [
                ReplySuggestion("稳妥回复", "我先核对一下当前信息，确认后给你一个明确的回复。", "low", "verify"),
                ReplySuggestion("简短回复", "收到，我处理后尽快回复你。", "low", "verify"),
                ReplySuggestion("边界回复", "这个事项我需要先确认时间和影响范围，再给你准确安排。", "medium", "verify"),
            ],
            "Local Preview",
        )
    )
    app.processEvents()
    grab_widget(main_window, out / "main_window.png")
    main_window._select_page("contacts")
    app.processEvents()
    grab_widget(main_window, out / "contacts_page.png")
    main_window._select_page("strategies")
    app.processEvents()
    grab_widget(main_window, out / "strategies_page.png")
    main_window._select_page("memories")
    app.processEvents()
    grab_widget(main_window, out / "memories_page.png")
    main_window._select_page("settings")
    app.processEvents()
    main_window._ai_provider.setCurrentText("Local Model")
    main_window._ai_model.setText("whochat-smoke-model")
    main_window._ai_base_url.setText("https://api.example.com/v1")
    main_window._save_ai_settings()
    config_path = out / "config" / "config.json"
    if "whochat-smoke-model" not in config_path.read_text(encoding="utf-8"):
        raise RuntimeError("AI settings were not persisted")
    grab_widget(main_window, out / "settings_page.png")
    main_window._select_page("diagnostics")
    app.processEvents()
    grab_widget(main_window, out / "diagnostics_page.png")
    grab_widget(floating, out / "floating_widget.png")

    main_window._render_reply_suggestions(
        ReplyGenerationResult(
            True,
            "local_preview",
            [ReplySuggestion("烟测", "烟测真实建议文本", "low", "verify")],
            "Local Preview",
        )
    )
    app.processEvents()
    suggestion_buttons = [button for button in floating.findChildren(QPushButton) if button.objectName() == "FloatingSuggestionButton"]
    target = suggestion_buttons[0]
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target.rect().center())
    app.processEvents()
    clipboard_text = QApplication.clipboard().text()
    if clipboard_text != "烟测真实建议文本":
        raise RuntimeError(
            "copy button did not populate real floating suggestion: "
            f"clipboard={clipboard_text!r} enabled={target.isEnabled()} "
            f"reply_text={target.property('reply_text')!r} status={floating.status_label.text()!r} "
            f"tooltip={floating.status_label.toolTip()!r}"
        )

    floating.hide_by_user()
    floating.attach_to_window_rect((100, 100, 900, 720), "微信")
    app.processEvents()
    if floating.isVisible():
        raise RuntimeError("floating widget reappeared after user hide")

    print(f"main_window={out / 'main_window.png'}")
    print(f"contacts_page={out / 'contacts_page.png'}")
    print(f"strategies_page={out / 'strategies_page.png'}")
    print(f"memories_page={out / 'memories_page.png'}")
    print(f"settings_page={out / 'settings_page.png'}")
    print(f"floating_widget={out / 'floating_widget.png'}")
    print(f"clipboard={clipboard_text}")
    QTimer.singleShot(0, app.quit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
