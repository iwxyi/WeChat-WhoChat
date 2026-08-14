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

DATA_DIR = ROOT / "tmp" / "reply_context_freshness_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.ai.models import ReplyGenerationResult, ReplySuggestion
from whochat.app import create_app
from whochat.core.models import ContactStatus, Message, Speaker
from whochat.core.runtime import PageClassification, PageType
from whochat.ocr.models import ParsedOcrMessage
from whochat.core.runtime import Rect
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.reply import context_hash
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("上下文新鲜度")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    for index in range(35):
        services.messages.add_message(
            Message(
                id=f"history-{index}",
                contact_id=contact.id,
                speaker=Speaker.OTHER,
                text=f"历史消息 {index}",
                content_type="text",
                ocr_confidence=0.9,
                observed_at=f"2026-01-01T00:00:{index:02d}+00:00",
                message_time=None,
                time_source="observed",
                partial=False,
                fingerprint=f"history-{index}",
                source="verify",
            )
        )
    runtime = services.runtime.update_from_window_info(
        WindowInfo(hwnd=71, title="微信", process_name="Weixin", rect=(20, 20, 1220, 820), visible=True)
    )
    services.runtime._state = replace(runtime, page=PageClassification(PageType.CHAT_DM, 0.9, "verify"), pipeline_status="finished:chat_dm")
    window = MainWindow(services)
    window._set_active_capture_contact(contact, 71)

    before = window._build_reply_context()
    if before.messages[-1].text != "历史消息 34":
        raise RuntimeError(f"latest stored message was omitted: {before.messages[-1].text}")
    before_hash = context_hash(before)

    window._last_ocr_contact_id = contact.id
    window._last_ocr_result_meta = {"created_at": "2026-01-01T01:00:00+00:00"}
    window._last_ocr_messages = [
        ParsedOcrMessage(Speaker.OTHER, "刚刚新增的当前消息", Rect(10, 10, 240, 44), 0.95, False, "verify"),
    ]
    after = window._build_reply_context()
    if after.messages[-1].text != "刚刚新增的当前消息":
        raise RuntimeError(f"live OCR message was not appended: {after.messages[-1].text}")
    if context_hash(after) == before_hash:
        raise RuntimeError("live OCR message did not change the reply context hash")

    window._suggestion_result = ReplyGenerationResult(
        True,
        "local_preview",
        [ReplySuggestion("旧建议", "历史上下文建议", "low", "verify")],
        "Local Preview",
    )
    window._suggestion_context_hash = before_hash
    window._refresh_reply_suggestions(automatic=True)
    deadline = time.monotonic() + 5
    fresh_hash = context_hash(after)
    while window._suggestion_context_hash != fresh_hash and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if services.reply_tasks.last_result is None:
        raise RuntimeError("fresh OCR context did not schedule a new AI request")
    if window._suggestion_context_hash != fresh_hash:
        raise RuntimeError("new AI request did not retain the fresh context hash")

    print(
        f"history_latest={before.messages[-1].text} live_latest={after.messages[-1].text} "
        f"count={len(after.messages)} ai_job={services.reply_tasks.last_result.job_id}"
    )
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
