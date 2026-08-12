from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "reply_stale_ui_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QPushButton

from whochat.ai.models import ReplyGenerationResult, ReplySuggestion
from whochat.app import create_app
from whochat.core.models import ContactStatus
from whochat.core.runtime import PageClassification, PageType
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.reply_tasks import ReplyTaskResult
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    first = services.contacts.create_or_get_by_display_name("异步旧联系人")
    first = services.contacts.update_profile(first.id, status=ContactStatus.CONFIRMED)
    second = services.contacts.create_or_get_by_display_name("当前联系人")
    second = services.contacts.update_profile(second.id, status=ContactStatus.CONFIRMED)

    runtime = services.runtime.update_from_window_info(
        WindowInfo(hwnd=920, title="微信", process_name="Weixin", rect=(80, 60, 1280, 860), visible=True)
    )
    runtime = replace(
        runtime,
        page=PageClassification(PageType.CHAT_DM, 0.78, "verify chat page"),
        visible_message_count=1,
        pipeline_status="finished:chat_dm",
    )
    services.runtime._state = runtime

    window = MainWindow(services)
    window._config.ai.provider = "Local Preview"
    window._config.ai.api_key = ""
    floating = FloatingWidget()
    window.attach_floating_widget(floating)
    window._set_active_capture_contact(second, runtime.window.hwnd)
    window._reload_contact_list(second.id)
    window._render_contact_detail(second)
    window._refresh_overview_data()

    stale_task = ReplyTaskResult(
        job_id=1,
        contact_id=first.id,
        hwnd=runtime.window.hwnd,
        result=ReplyGenerationResult(
            True,
            "local_preview",
            [ReplySuggestion("旧建议", "这条旧建议不应该展示", "low", "verify")],
            "Local Preview",
        ),
    )
    window._on_reply_task_ready(stale_task)
    buttons = [button for button in floating.findChildren(QPushButton) if button.objectName() == "FloatingSuggestionButton"]
    if window._suggestion_result is None or window._suggestion_result.allowed:
        raise RuntimeError(f"stale result should be blocked: {window._suggestion_result}")
    if window._suggestion_result.status != "blocked:reply_context_changed":
        raise RuntimeError(f"unexpected stale status: {window._suggestion_result.status}")
    if any(button.isEnabled() for button in buttons):
        raise RuntimeError("stale reply result should disable floating suggestion buttons")
    if any("旧建议" in button.text() or button.property("reply_text") for button in buttons):
        raise RuntimeError("stale reply text leaked into floating buttons")

    matching_task = ReplyTaskResult(
        job_id=2,
        contact_id=second.id,
        hwnd=runtime.window.hwnd,
        result=ReplyGenerationResult(
            True,
            "local_preview",
            [ReplySuggestion("新建议", "这是当前联系人建议", "low", "verify")],
            "Local Preview",
        ),
    )
    window._on_reply_task_ready(matching_task)
    if window._suggestion_result is None or not window._suggestion_result.allowed:
        raise RuntimeError(f"matching result should render: {window._suggestion_result}")
    if not buttons[0].isEnabled() or buttons[0].property("reply_text") != "这是当前联系人建议":
        raise RuntimeError("matching reply result did not update floating buttons")

    print(f"stale={stale_task.contact_id} current={second.id} matching_enabled={buttons[0].isEnabled()}")
    window.close()
    floating.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
