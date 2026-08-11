from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "group_members_ui_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.core.models import ConversationType, IdentityStatus
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    group = services.contacts.create_or_get_by_display_name(
        "项目群",
        platform="wechat",
        conversation_type=ConversationType.GROUP,
    )
    friend = services.contacts.create_or_get_by_display_name("小蓝", platform="wechat", conversation_type=ConversationType.DM)
    person = services.identities.create_person("蓝同学", status=IdentityStatus.CONFIRMED)
    services.identities.add_person_alias(person.id, "小蓝", "manual")
    services.identities.link_contact_to_person(friend.id, person.id, confidence=1.0, source="manual", verified=True)
    services.identities.add_group_member(
        group_contact_id=group.id,
        member_display_name="小蓝",
        person_id=person.id,
        platform_contact_id=friend.id,
        confidence=0.96,
        source="manual",
    )
    services.identities.add_group_member(
        group_contact_id=group.id,
        member_display_name="产品同学",
        confidence=0.35,
        source="ocr",
    )

    window = MainWindow(services)
    window._render_contact_detail(group)
    text = window._contact_members_text.toPlainText()
    if "项目群" not in text or "小蓝" not in text or "蓝同学" not in text or "wechat·小蓝" not in text:
        raise RuntimeError(f"group members tab missing linked member detail: {text}")
    if "产品同学" not in text or "未链接" not in text:
        raise RuntimeError(f"group members tab missing unresolved member detail: {text}")
    print(f"group_members_text_chars={len(text)}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
