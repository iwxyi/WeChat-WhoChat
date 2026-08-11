from __future__ import annotations

import os
import shutil
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "reply_feedback_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.ai.models import ReplyGenerationResult, ReplySuggestion
from whochat.app import create_app
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.storage.repositories import new_id
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("反馈联系人", platform="wechat")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    services.messages.add_message(
        Message(
            id=new_id("message"),
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="请帮我确认。",
            content_type="text",
            ocr_confidence=0.96,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="reply-feedback-message",
            source="verify",
        )
    )
    window = MainWindow(services)
    services.runtime.update_from_window_info(
        WindowInfo(hwnd=7701, title="微信", process_name="Weixin.exe", rect=(40, 40, 1240, 840), visible=True)
    )
    services.runtime._state = services.runtime.state.__class__(
        window=services.runtime.state.window,
        layout=services.runtime.state.layout,
        page=PageClassification(PageType.CHAT_DM, 0.9, "verify chat page"),
        capture_decision=services.runtime.state.capture_decision,
        paused=services.runtime.state.paused,
        last_snapshot_hash=services.runtime.state.last_snapshot_hash,
        visible_message_count=services.runtime.state.visible_message_count,
        pipeline_status=services.runtime.state.pipeline_status,
    )
    window._reload_contact_list(contact.id)
    suggestion = ReplySuggestion("稳妥版", "这条回复文本会被截断保存到 preview 字段。" * 5, "low", "验证反馈")
    window._render_reply_suggestions(ReplyGenerationResult(True, "local_preview", [suggestion], "Local Preview"))
    window._record_reply_feedback(suggestion, "useful")
    window._record_reply_feedback(suggestion, "bad")

    rows = services.reply_feedback.tail(10)
    if len(rows) != 2:
        raise RuntimeError(f"expected two feedback records, got {len(rows)}")
    values = {row.feedback for row in rows}
    if values != {"useful", "bad"}:
        raise RuntimeError(f"feedback values mismatch: {values}")
    if any(row.contact_id != contact.id or row.context_hash == "" for row in rows):
        raise RuntimeError(f"feedback did not persist contact/context: {rows}")
    if any(len(row.suggestion_text_preview) > 96 for row in rows):
        raise RuntimeError(f"feedback should only persist preview text: {rows}")
    feedback_text = window._contact_feedback_text.toPlainText()
    if "最近反馈：2 条" not in feedback_text or "好用 1" not in feedback_text or "不合适 1" not in feedback_text:
        raise RuntimeError(f"contact detail should refresh after reply feedback: {feedback_text}")
    if "这条回复文本会被截断保存到 preview 字段" not in feedback_text or "context=" not in feedback_text:
        raise RuntimeError(f"contact detail should show feedback evidence without full payload: {feedback_text}")
    diagnostics_text = window._format_reply_feedback_lines(10)
    if "回复反馈：count=2 useful=1 bad=1" not in diagnostics_text:
        raise RuntimeError(f"diagnostics feedback summary should refresh after feedback: {diagnostics_text}")

    export_path = services.governance.export_contact(contact.id)
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    if len(payload.get("reply_feedback", [])) != 2:
        raise RuntimeError(f"contact export should include reply feedback: {payload.keys()}")
    cleared = services.governance.clear_contact_data(contact.id)
    if cleared.reply_feedback_deleted != 2 or services.reply_feedback.list_for_contact(contact.id):
        raise RuntimeError(f"contact clear should remove reply feedback: {cleared}")

    print(f"reply_feedback={len(rows)} latest={rows[0].feedback} cleared={cleared.reply_feedback_deleted}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
