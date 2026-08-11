from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["WHOCHAT_DATA_DIR"] = str(ROOT / "tmp" / "storage_verify")
os.environ["WHOCHAT_DB_PATH"] = str(ROOT / "tmp" / "storage_verify" / "whochat.db")

from whochat.core.models import ContactStatus, ConversationType, MemoryKind, MemoryStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import TargetApp, ThemeMode
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.storage.repositories import new_id


def main() -> int:
    services = build_services()
    strategies = services.strategies.list_all()
    if not any(strategy.id == "manual_protect" and strategy.requires_manual_reply for strategy in strategies):
        raise RuntimeError("default manual protection strategy missing")

    custom = services.strategies.create(
        name="验证分组",
        goal="验证用户可自定义目标",
        mode="验证",
        tone="专业、克制",
        avoid="泄露隐私",
        reply_variants="稳妥版,边界版",
        requires_manual_reply=False,
    )
    updated_custom = services.strategies.update(
        custom.__class__(
            id=custom.id,
            name="验证分组-已更新",
            goal="验证目标可被持久化更新",
            mode=custom.mode,
            tone=custom.tone,
            avoid=custom.avoid,
            reply_variants=custom.reply_variants,
            requires_manual_reply=True,
            created_at=custom.created_at,
            updated_at=custom.updated_at,
        )
    )
    if not updated_custom.requires_manual_reply or services.strategies.get(custom.id).goal != "验证目标可被持久化更新":
        raise RuntimeError("strategy create/update failed")

    contact = services.contacts.create_or_get_by_display_name("测试联系人")
    if contact.display_name != "测试联系人":
        raise RuntimeError("contact was not created")
    contact = services.contacts.update_profile(
        contact.id,
        status=ContactStatus.CONFIRMED,
        strategy_id=updated_custom.id,
        remark="验证备注",
    )
    if contact.status != ContactStatus.CONFIRMED or contact.strategy_id != updated_custom.id or contact.remark != "验证备注":
        raise RuntimeError("contact profile update failed")

    group_contact = services.contacts.create_or_get_by_display_name(
        "项目群",
        conversation_type=ConversationType.GROUP,
    )
    group_contact = services.contacts.update_profile(group_contact.id, status=ContactStatus.CONFIRMED, strategy_id=updated_custom.id)
    if group_contact.conversation_type != ConversationType.GROUP or group_contact.strategy_id != updated_custom.id:
        raise RuntimeError("group chat should use the same strategy assignment model as DM contacts")

    fingerprint = f"verify-message-{uuid.uuid4().hex}"
    message = Message(
        id=new_id("message"),
        contact_id=contact.id,
        speaker=Speaker.OTHER,
        text="这是一条用于验证的消息",
        content_type="text",
        ocr_confidence=0.99,
        observed_at=utc_now_iso(),
        message_time=None,
        time_source="observed",
        partial=False,
        fingerprint=fingerprint,
        source="storage_verify",
    )
    inserted = services.messages.add_message(message)
    duplicate = services.messages.add_message(message)
    if not inserted or duplicate:
        raise RuntimeError("message insert/dedup failed")

    memory = services.memories.add_pending(contact.id, MemoryKind.FACT, "测试联系人喜欢简洁回复", 0.9)
    memories = services.memories.list_for_contact(contact.id)
    if memory.id not in {item.id for item in memories}:
        raise RuntimeError("memory was not persisted")
    services.memories.update_status(memory.id, MemoryStatus.CONFIRMED)
    confirmed = services.memories.list_by_status(MemoryStatus.CONFIRMED)
    if memory.id not in {item.id for item in confirmed}:
        raise RuntimeError("memory confirm failed")
    rejected = services.memories.add_pending(contact.id, MemoryKind.AVOID, "这是一条应拒绝的记忆", 0.2)
    services.memories.update_status(rejected.id, MemoryStatus.REJECTED)
    if rejected.id not in {item.id for item in services.memories.list_by_status(MemoryStatus.REJECTED)}:
        raise RuntimeError("memory reject failed")

    services.logs.append("info", "verify", "storage_verified", "Storage verification passed")
    logs = services.logs.tail(10)
    if not any(log.event == "storage_verified" for log in logs):
        raise RuntimeError("log was not persisted")

    runtime_state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=1, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    if runtime_state.layout is None:
        raise RuntimeError("runtime layout missing for calibration verification")
    calibration = services.calibrations.create_from_layout(
        name="验证校准",
        target=TargetApp.WECHAT,
        window_rect=runtime_state.window.rect,
        layout=runtime_state.layout,
        theme=ThemeMode.UNKNOWN,
        active=True,
    )
    active = services.calibrations.get_active(TargetApp.WECHAT)
    if active is None or active.id != calibration.id:
        raise RuntimeError("active calibration was not persisted")
    calibrated_state = services.runtime.refresh_current()
    if calibrated_state.layout is None or calibrated_state.layout.source.value != "calibrated":
        raise RuntimeError("runtime did not use active calibration")

    print(f"db={services.db.path}")
    print(f"strategies={len(strategies)} chat_objects={len(services.contacts.list_recent())} memories={len(memories)} logs={len(logs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
