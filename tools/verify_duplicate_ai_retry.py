from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "duplicate_ai_retry_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.ai.models import ReplyGenerationResult
from whochat.app import create_app
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("重复截图重试")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    services.messages.add_message(
        Message(
            id="retry-message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="请确认一下最新情况。",
            content_type="text",
            ocr_confidence=0.9,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="retry-message",
            source="verify",
        )
    )
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=811, title="微信", process_name="Weixin", rect=(20, 20, 1220, 820), visible=True)
    )
    confirmed_page = PageClassification(PageType.CHAT_DM, 0.9, "verified chat")
    services.runtime._last_confirmed_page = confirmed_page
    services.runtime._state = replace(state, page=PageClassification(PageType.UNKNOWN, 0.1, "refresh"), visible_message_count=1)

    window = MainWindow(services)
    window._config.ai.provider = "Local Preview"
    window._config.ai.api_key = ""
    window._set_active_capture_contact(contact, 811)
    window._suggestion_result = ReplyGenerationResult(False, "provider_error: temporary", [], "Local Preview")
    services.pipeline.result_discarded.emit("duplicate_snapshot:verify")

    deadline = time.monotonic() + 5
    while services.reply_tasks.last_result is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if services.runtime.state.page.page_type != PageType.CHAT_DM:
        raise RuntimeError(f"duplicate snapshot did not retain the confirmed page: {services.runtime.state.page}")
    if services.reply_tasks.last_result is None or not services.reply_tasks.last_result.result.allowed:
        raise RuntimeError(f"duplicate snapshot did not retry failed AI result: {services.reply_tasks.last_result}")

    print(f"page={services.runtime.state.page.page_type.value} retry_job={services.reply_tasks.last_result.job_id}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
