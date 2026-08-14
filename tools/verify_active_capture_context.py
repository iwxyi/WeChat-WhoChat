from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "active_capture_context_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QPushButton

from whochat.ai.models import ReplyGenerationResult, ReplySuggestion
from whochat.app import create_app
from whochat.core.models import ContactStatus
from whochat.core.runtime import CaptureDecision, PageClassification, PageType, WindowState
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.reply_tasks import ReplyTaskResult
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    captured = services.contacts.create_or_get_by_display_name("当前采集对象")
    captured = services.contacts.update_profile(captured.id, status=ContactStatus.CONFIRMED)
    browsed = services.contacts.create_or_get_by_display_name("仅浏览对象")
    browsed = services.contacts.update_profile(browsed.id, status=ContactStatus.CONFIRMED)
    runtime = services.runtime.update_from_window_info(
        WindowInfo(hwnd=301, title="微信", process_name="Weixin", rect=(20, 20, 1220, 820), visible=True)
    )
    services.runtime._state = replace(runtime, page=PageClassification(PageType.CHAT_DM, 0.9, "verify"), pipeline_status="finished:chat_dm")

    window = MainWindow(services)
    floating = FloatingWidget()
    window.attach_floating_widget(floating)
    window._set_active_capture_contact(captured, 301)
    window._reload_contact_list(browsed.id)
    window._render_contact_detail(browsed)
    window._sync_floating_content()
    if "当前采集对象" not in floating.contact_label.text():
        raise RuntimeError(f"floating used browsed contact instead of active capture contact: {floating.contact_label.text()}")

    allowed = ReplyGenerationResult(True, "local_preview", [ReplySuggestion("建议", "仅当前对象可复制", "low", "verify")], "Local Preview")
    window._render_reply_suggestions(allowed)
    buttons = [item for item in floating.findChildren(QPushButton) if item.objectName() == "FloatingSuggestionButton"]
    if not buttons[0].isEnabled():
        raise RuntimeError("active capture suggestion should be copyable")

    window._render_reply_suggestions(ReplyGenerationResult(False, "blocked:provider_backoff", [], "Local Preview"))
    if window._suggestion_result is None or not window._suggestion_result.allowed:
        raise RuntimeError("a blocked replacement should retain the prior valid suggestion")
    if buttons[0].property("reply_text") != "仅当前对象可复制":
        raise RuntimeError("blocked replacement cleared the floating suggestion")
    window._config.ai.provider = "Disabled"
    window._sync_floating_content()
    if not buttons[0].isEnabled() or buttons[0].property("reply_text") != "仅当前对象可复制":
        raise RuntimeError("blocked status should not clear the prior floating suggestion")
    window._config.ai.provider = "Local Preview"

    services.runtime._state = replace(
        services.runtime.state,
        ocr_pending=True,
        pipeline_status="running",
        capture_decision=CaptureDecision(False, "OCR worker is running"),
    )
    window.update_runtime_state(services.runtime.state)
    if window._suggestion_result is None or not window._suggestion_result.allowed:
        raise RuntimeError("OCR refresh should retain the current conversation suggestion")
    if not buttons[0].isEnabled():
        raise RuntimeError("OCR refresh should keep the current conversation suggestion copyable")

    services.runtime._state = replace(
        services.runtime.state,
        ocr_pending=False,
        pipeline_status="finished:chat_dm",
    )

    services.runtime.update_from_window_info(None)
    if window._active_capture_contact() is not None or window._suggestion_result is not None:
        raise RuntimeError("missing window must clear active contact and old reply")
    if any(button.isEnabled() or button.property("reply_text") for button in buttons):
        raise RuntimeError("missing window leaked copyable reply text")

    restored = services.runtime.update_from_window_info(
        WindowInfo(hwnd=301, title="微信", process_name="Weixin", rect=(20, 20, 1220, 820), visible=True)
    )
    services.runtime._state = replace(restored, page=PageClassification(PageType.CHAT_DM, 0.9, "verify"), ocr_pending=True, pipeline_status="running")
    window.update_runtime_state(services.runtime.state)
    if window._suggestion_result is not None or window._active_capture_contact() is not None:
        raise RuntimeError("new OCR round must not retain prior conversation suggestion")
    if any(button.isEnabled() for button in buttons):
        raise RuntimeError("new OCR round must disable reply copying until title confirmation")
    delayed = ReplyTaskResult(
        job_id=9,
        contact_id=captured.id,
        hwnd=301,
        window_title="微信",
        result=ReplyGenerationResult(True, "local_preview", [ReplySuggestion("旧", "不能出现", "low", "verify")], "Local Preview"),
    )
    window._on_reply_task_ready(delayed)
    if window._suggestion_result is None or window._suggestion_result.status != "blocked:reply_context_changed":
        raise RuntimeError("reply returned for an unconfirmed new conversation should be blocked")
    if any(button.isEnabled() or button.property("reply_text") for button in buttons):
        raise RuntimeError("delayed reply leaked into floating controls during OCR recheck")

    print("active_contact_binding=passed blocked_retained=passed ocr_refresh_retained=passed window_clear=passed new_ocr_clear=passed delayed_reply=blocked")
    window.close()
    floating.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
