from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "contact_action_sync_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("动作同步联系人")
    services.messages.add_message(
        Message(
            id="contact_action_sync_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="帮我确认一下。",
            content_type="text",
            ocr_confidence=0.91,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="contact_action_sync_fp",
            source="verify",
        )
    )
    services.runtime._state = replace(
        missing_runtime_state(),
        page=PageClassification(PageType.CHAT_DM, 0.92, "verify chat page"),
        pipeline_status="finished:chat_dm",
        visible_message_count=1,
    )
    window = MainWindow(services)
    floating = FloatingWidget()
    window.attach_floating_widget(floating)
    window._reload_contact_list(contact.id)
    window._render_contact_detail(contact)

    window._update_selected_contact_status(ContactStatus.CONFIRMED)
    confirmed = services.contacts.get(contact.id)
    if confirmed is None or confirmed.status != ContactStatus.CONFIRMED:
        raise RuntimeError("confirm action did not persist contact status")
    selected_text = window._contact_list.currentItem().text()
    if "confirmed" not in selected_text:
        raise RuntimeError(f"contact list did not refresh confirmed status: {selected_text}")
    if window._overview_contact_values["status"].text() != "confirmed":
        raise RuntimeError("overview contact status did not refresh after confirm")
    if "动作同步联系人" not in floating.contact_label.text():
        raise RuntimeError(f"floating context did not track confirmed contact: {floating.contact_label.text()}")

    window._protect_selected_contact()
    protected = services.contacts.get(contact.id)
    if protected is None or protected.strategy_id != "manual_protect" or protected.status != ContactStatus.CONFIRMED:
        raise RuntimeError(f"manual protection did not persist expected profile: {protected}")
    if "手动回复保护" not in window._overview_contact_values["strategy"].text():
        raise RuntimeError("overview strategy did not show manual protection")
    result = window._build_reply_result()
    if result.allowed or "手动回复保护" not in result.status:
        raise RuntimeError(f"manual protection should block copyable replies: {result}")
    if "手动回复保护" not in floating.contact_label.text():
        raise RuntimeError(f"floating group did not refresh manual protection: {floating.contact_label.text()}")

    print(f"contact={protected.display_name} status={protected.status.value} strategy={protected.strategy_id}")
    floating.close()
    window.close()
    services.shutdown()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
