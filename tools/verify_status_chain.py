from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "status_chain_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.config import AppConfig
from whochat.core.models import ContactStatus
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.status import build_status_chain


def main() -> int:
    services = build_services()
    config = AppConfig()
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=1, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    state = replace(state, page=PageClassification(PageType.UNKNOWN, 0.1, "verify unknown page"))
    contact = services.contacts.create_or_get_by_display_name("Status Contact")
    strategy = services.strategies.get(contact.strategy_id)
    unknown_steps = build_status_chain(
        runtime=state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(unknown_steps, "页面", "待确认")
    _assert_step(unknown_steps, "AI", "阻断")
    _assert_action_contains(unknown_steps, "页面", "立即采集")
    _assert_no_text(unknown_steps, "仅从窗口标题无法确认")

    chat_state = replace(state, page=PageClassification(PageType.CHAT_DM, 0.9, "verify chat"))
    unconfirmed_steps = build_status_chain(
        runtime=chat_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(unconfirmed_steps, "联系人", "通过")
    _assert_action_contains(unconfirmed_steps, "联系人", "合并")

    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, allow_cloud_ai=False)
    config.ai.api_key = "sk-test-value-that-must-not-be-used"
    unauthorized_steps = build_status_chain(
        runtime=chat_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(unauthorized_steps, "隐私", "阻断")
    _assert_action_contains(unauthorized_steps, "隐私", "云端")

    contact = services.contacts.update_profile(contact.id, allow_cloud_ai=True)
    ready_steps = build_status_chain(
        runtime=chat_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(ready_steps, "AI", "就绪")
    _assert_action_contains(ready_steps, "AI", "生成建议")
    _assert_step(ready_steps, "OCR", "等待")

    running_ocr_state = replace(chat_state, ocr_pending=True, pipeline_status="running")
    running_ocr_steps = build_status_chain(
        runtime=running_ocr_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(running_ocr_steps, "OCR", "运行中")

    title_ready_state = replace(chat_state, ocr_pending=True, pipeline_status="title_ready")
    title_ready_steps = build_status_chain(
        runtime=title_ready_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(title_ready_steps, "OCR", "读取消息")
    _assert_action_contains(title_ready_steps, "OCR", "等待消息")

    finished_ocr_state = replace(chat_state, pipeline_status="finished:chat_dm", visible_message_count=3)
    finished_ocr_steps = build_status_chain(
        runtime=finished_ocr_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(finished_ocr_steps, "OCR", "通过")

    failed_ocr_state = replace(chat_state, pipeline_status="discarded:pipeline_failed:PaddleOCR 超时")
    failed_ocr_steps = build_status_chain(
        runtime=failed_ocr_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(failed_ocr_steps, "OCR", "失败")

    cooled_ocr_state = replace(chat_state, pipeline_status="discarded:flow_cooldown:100ms")
    cooled_ocr_steps = build_status_chain(
        runtime=cooled_ocr_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=False,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(cooled_ocr_steps, "OCR", "等待")

    running_steps = build_status_chain(
        runtime=chat_state,
        contact=contact,
        strategy=strategy,
        config=config,
        reply_running=True,
        provider_health=services.reply_generator.provider_health_summary(),
    )
    _assert_step(running_steps, "AI", "运行中")

    print(" | ".join(f"{step.stage}:{step.state}" for step in ready_steps))
    return 0


def _assert_step(steps, stage: str, state: str) -> None:
    match = next((step for step in steps if step.stage == stage), None)
    if match is None:
        raise RuntimeError(f"missing stage: {stage}")
    if match.state != state:
        raise RuntimeError(f"unexpected state for {stage}: {match.state}, expected {state}; reason={match.reason}")


def _assert_action_contains(steps, stage: str, text: str) -> None:
    match = next((step for step in steps if step.stage == stage), None)
    if match is None:
        raise RuntimeError(f"missing stage: {stage}")
    if text not in match.action:
        raise RuntimeError(f"unexpected action for {stage}: {match.action}, expected to contain {text}")


def _assert_no_text(steps, text: str) -> None:
    combined = "\n".join(f"{step.stage} {step.state} {step.reason} {step.action}" for step in steps)
    if text in combined:
        raise RuntimeError(f"status chain still contains stale text: {text}")


if __name__ == "__main__":
    raise SystemExit(main())
