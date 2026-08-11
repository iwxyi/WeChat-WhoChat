from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "identity_model_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.core.models import ConversationType, IdentityStatus
from whochat.services.bootstrap import build_services


def main() -> int:
    services = build_services()
    wechat_alice = services.contacts.create_or_get_by_display_name("小王", platform="wechat")
    telegram_alice = services.contacts.create_or_get_by_display_name("Alice W.", platform="telegram")
    same_name_other = services.contacts.create_or_get_by_display_name("小王", platform="discord")
    group = services.contacts.create_or_get_by_display_name(
        "项目推进群",
        platform="wechat",
        conversation_type=ConversationType.GROUP,
    )

    person = services.identities.create_person("王晓明", status=IdentityStatus.CONFIRMED)
    services.identities.add_person_alias(person.id, "小王", "manual")
    services.identities.add_person_alias(person.id, "Alice W.", "manual")
    services.identities.link_contact_to_person(wechat_alice.id, person.id, confidence=1.0, source="manual", verified=True)
    services.identities.link_contact_to_person(telegram_alice.id, person.id, confidence=0.95, source="manual", verified=True)

    stranger = services.identities.create_person("另一个小王", status=IdentityStatus.SUSPECTED)
    services.identities.add_person_alias(stranger.id, "小王", "manual")
    services.identities.link_contact_to_person(same_name_other.id, stranger.id, confidence=0.6, source="manual", verified=False)

    linked_member = services.identities.add_group_member(
        group_contact_id=group.id,
        member_display_name="小王",
        person_id=person.id,
        platform_contact_id=wechat_alice.id,
        confidence=0.92,
        source="manual",
    )
    unknown_member = services.identities.add_group_member(
        group_contact_id=group.id,
        member_display_name="产品同学",
        confidence=0.35,
        source="ocr",
    )

    people_named_xw = services.identities.find_people_by_alias("小王")
    if {item.id for item in people_named_xw} != {person.id, stranger.id}:
        raise RuntimeError("same nickname should be allowed to resolve to multiple people")
    linked_people = services.identities.list_people_for_contact(wechat_alice.id)
    if not linked_people or linked_people[0][0].id != person.id or not linked_people[0][1].verified:
        raise RuntimeError("wechat contact should link to confirmed person")
    telegram_people = services.identities.list_people_for_contact(telegram_alice.id)
    if not telegram_people or telegram_people[0][0].id != person.id:
        raise RuntimeError("cross-platform contact should link to same person")
    members = services.identities.list_group_members(group.id)
    if {member.member_display_name for member in members} != {"小王", "产品同学"}:
        raise RuntimeError(f"group members mismatch: {members}")
    if linked_member.person_id != person.id or linked_member.platform_contact_id != wechat_alice.id:
        raise RuntimeError("group member should optionally overlap with friend contact")
    if unknown_member.person_id is not None or unknown_member.platform_contact_id is not None:
        raise RuntimeError("unresolved group member should remain independent")

    print(f"people={len(people_named_xw)} links={len(linked_people) + len(telegram_people)} group_members={len(members)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
