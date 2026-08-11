from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "reply_explainability_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.ai.models import ReplyGenerationResult, ReplySuggestion
from whochat.app import create_app
from whochat.core.models import ContactStatus, MemoryKind, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.storage.repositories import new_id
from whochat.ui.main_window import MainWindow
from PySide6.QtWidgets import QLabel


def main() -> int:
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("解释性联系人", platform="wechat")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, allow_cloud_ai=True)
    services.memories.add_pending(contact.id, MemoryKind.FACT, "偏好简短明确", 0.91)
    services.messages.add_message(
        Message(
            id=new_id("message"),
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="今天能确认吗？",
            content_type="text",
            ocr_confidence=0.98,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="reply-explainability-message",
            source="verify",
        )
    )

    window = MainWindow(services)
    services.runtime.update_from_window_info(
        WindowInfo(hwnd=6601, title="微信", process_name="Weixin.exe", rect=(40, 40, 1240, 840), visible=True)
    )
    services.runtime._state = services.runtime.state.__class__(
        window=services.runtime.state.window,
        layout=services.runtime.state.layout,
        page=PageClassification(PageType.CHAT_DM, 0.88, "verify chat page"),
        capture_decision=services.runtime.state.capture_decision,
        paused=services.runtime.state.paused,
        last_snapshot_hash=services.runtime.state.last_snapshot_hash,
        visible_message_count=services.runtime.state.visible_message_count,
        pipeline_status=services.runtime.state.pipeline_status,
    )
    window._reload_contact_list(contact.id)
    allowed = ReplyGenerationResult(
        True,
        "local_preview",
        [ReplySuggestion("稳妥版", "我先确认一下。", "low", "目标：稳妥；语气：清晰。")],
        "Local Preview",
    )
    window._render_reply_suggestions(allowed)
    panel_text = _panel_text(window)
    if "依据：wechat·解释性联系人" not in panel_text or "消息 1" not in panel_text or "记忆 1" not in panel_text:
        raise RuntimeError(f"reply evidence summary missing context: {panel_text}")
    if "chat_dm" not in panel_text or "允许云端" not in panel_text:
        raise RuntimeError(f"reply evidence summary missing page/cloud state: {panel_text}")
    if "low · 目标：稳妥" not in panel_text:
        raise RuntimeError(f"suggestion rationale should be visible and compact: {panel_text}")

    ignored = services.contacts.update_profile(contact.id, status=ContactStatus.IGNORED)
    window._reload_contact_list(ignored.id)
    blocked = window._build_reply_result()
    window._render_reply_suggestions(blocked)
    blocked_text = _panel_text(window)
    if "已阻断" not in blocked_text or "已被忽略" not in blocked_text:
        raise RuntimeError(f"blocked reply state should remain explicit: {blocked_text}")
    if "依据：wechat·解释性联系人" not in blocked_text:
        raise RuntimeError(f"blocked reply state should still show evidence: {blocked_text}")

    print("reply_explainability=ok")
    window.close()
    app.quit()
    return 0


def _panel_text(window: MainWindow) -> str:
    return " ".join(label.text() for label in window._suggestions_panel.findChildren(QLabel))


if __name__ == "__main__":
    raise SystemExit(main())
