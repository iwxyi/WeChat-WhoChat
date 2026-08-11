from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "identity_ui_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.core.models import IdentityStatus
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    wechat = services.contacts.create_or_get_by_display_name("小红", platform="wechat")
    telegram = services.contacts.create_or_get_by_display_name("Big Red", platform="telegram")
    person = services.identities.create_person("红红本人", status=IdentityStatus.CONFIRMED)
    services.identities.add_person_alias(person.id, "小红", "manual")
    services.identities.add_person_alias(person.id, "Big Red", "manual")
    services.identities.link_contact_to_person(wechat.id, person.id, confidence=1.0, source="manual", verified=True)
    services.identities.link_contact_to_person(telegram.id, person.id, confidence=0.95, source="manual", verified=True)

    window = MainWindow(services)
    window._reload_contact_list(wechat.id)
    selected = None
    for index in range(window._contact_list.count()):
        item = window._contact_list.item(index)
        if item.data(0x0100) == wechat.id:
            selected = item
            break
    if selected is None:
        raise RuntimeError("wechat contact not found in UI list")
    if "wechat·小红" not in selected.text():
        raise RuntimeError(f"contact list should show platform-qualified name: {selected.text()}")
    window._on_contact_selected(selected)
    profile = window._contact_profile_text.toPlainText()
    if "聊天对象：wechat·小红" not in profile:
        raise RuntimeError(f"contact profile should show platform-qualified name: {profile}")
    text = window._contact_identity_text.toPlainText()
    if "红红本人" not in text or "Big Red" not in text or "verified=True" not in text:
        raise RuntimeError(f"identity tab did not render linked person: {text}")
    print(f"identity_text_chars={len(text)} person={person.id}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
