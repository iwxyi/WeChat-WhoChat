from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "ingestion_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.core.models import ContactStatus, ConversationType, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, Rect
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox, ParsedOcrMessage
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.pipeline import PipelineResult


def main() -> int:
    services = build_services()
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=901, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    if state.layout is None:
        raise RuntimeError("expected layout")

    result = PipelineResult(
        job_id=1,
        hwnd=901,
        target_app="wechat",
        app_label="微信",
        snapshot_hash="abc123",
        image_path=DATA_DIR / "capture.png",
        ocr_image_path=DATA_DIR / "capture_content.png",
        crop_rect=None,
        layout=state.layout,
        ocr_result=OcrResult(
            boxes=[
                OcrTextBox("Alice Zhang", _inside(state.layout.title_rect, 0.05, 0.2, 0.28, 0.72), 0.82, OcrRegion.UNKNOWN, "verify"),
                OcrTextBox("下午前能确认方案吗？", _inside(state.layout.message_rect, 0.08, 0.15, 0.42, 0.24), 0.88, OcrRegion.UNKNOWN, "verify"),
                OcrTextBox("我看一下后回复你。", _inside(state.layout.message_rect, 0.58, 0.34, 0.94, 0.43), 0.86, OcrRegion.UNKNOWN, "verify"),
            ],
            source_image=str(DATA_DIR / "capture.png"),
            engine="verify-ocr",
        ),
        page=PageClassification(PageType.CHAT_DM, 0.74, "verify chat page"),
        messages=[
            ParsedOcrMessage(Speaker.OTHER, "下午前能确认方案吗？", _inside(state.layout.message_rect, 0.08, 0.15, 0.42, 0.24), 0.88, False, "verify"),
            ParsedOcrMessage(Speaker.ME, "我看一下后回复你。", _inside(state.layout.message_rect, 0.58, 0.34, 0.94, 0.43), 0.86, False, "verify"),
        ],
        created_at=utc_now_iso(),
    )

    accepted = services.ingestion.ingest_pipeline_result(result)
    if not accepted.accepted or accepted.contact is None:
        raise RuntimeError(f"ingestion should accept chat result: {accepted}")
    if accepted.contact.status != ContactStatus.SUSPECTED:
        raise RuntimeError(f"new OCR contact should be suspected, got {accepted.contact.status}")
    if accepted.inserted_messages != 2:
        raise RuntimeError(f"expected 2 inserted messages, got {accepted.inserted_messages}")
    if accepted.contact.platform != "wechat":
        raise RuntimeError(f"wechat ingestion should store platform=wechat, got {accepted.contact.platform}")

    duplicate = services.ingestion.ingest_pipeline_result(result)
    if duplicate.inserted_messages != 0 or duplicate.duplicate_messages != 2:
        raise RuntimeError(f"expected duplicate messages to be ignored: {duplicate}")

    telegram_result = PipelineResult(
        **{
            **result.__dict__,
            "job_id": 22,
            "hwnd": 902,
            "target_app": "telegram",
            "app_label": "Telegram",
            "snapshot_hash": "telegram",
            "ocr_result": OcrResult(
                boxes=[
                    OcrTextBox("Alice Zhang", _inside(state.layout.title_rect, 0.05, 0.2, 0.28, 0.72), 0.82, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("Telegram 上也能确认吗？", _inside(state.layout.message_rect, 0.08, 0.15, 0.44, 0.24), 0.88, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("我稍后确认。", _inside(state.layout.message_rect, 0.58, 0.34, 0.90, 0.43), 0.86, OcrRegion.UNKNOWN, "verify"),
                ],
                source_image=str(DATA_DIR / "telegram.png"),
                engine="verify-ocr",
            ),
            "messages": [
                ParsedOcrMessage(Speaker.OTHER, "Telegram 上也能确认吗？", _inside(state.layout.message_rect, 0.08, 0.15, 0.44, 0.24), 0.88, False, "verify"),
                ParsedOcrMessage(Speaker.ME, "我稍后确认。", _inside(state.layout.message_rect, 0.58, 0.34, 0.90, 0.43), 0.86, False, "verify"),
            ],
        }
    )
    telegram_accepted = services.ingestion.ingest_pipeline_result(telegram_result)
    if not telegram_accepted.accepted or telegram_accepted.contact is None:
        raise RuntimeError(f"telegram ingestion should be accepted: {telegram_accepted}")
    if telegram_accepted.contact.platform != "telegram":
        raise RuntimeError(f"telegram ingestion should store platform=telegram, got {telegram_accepted.contact.platform}")
    if telegram_accepted.contact.id == accepted.contact.id:
        raise RuntimeError("same nickname from different apps should create separate platform contacts")

    blocked_result = PipelineResult(
        **{
            **result.__dict__,
            "job_id": 2,
            "snapshot_hash": "blocked",
            "page": PageClassification(PageType.UNKNOWN, 0.35, "verify unknown page"),
        }
    )
    blocked = services.ingestion.ingest_pipeline_result(blocked_result)
    if blocked.accepted:
        raise RuntimeError(f"unknown page should be blocked: {blocked}")

    missing_title_result = PipelineResult(
        **{
            **result.__dict__,
            "job_id": 23,
            "snapshot_hash": "missing_title",
            "ocr_result": OcrResult(
                boxes=[
                    OcrTextBox("微信", _inside(state.layout.title_rect, 0.05, 0.2, 0.18, 0.72), 0.91, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("这条消息不应该入库", _inside(state.layout.message_rect, 0.08, 0.15, 0.42, 0.24), 0.88, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("输入", _inside(state.layout.input_rect, 0.05, 0.2, 0.16, 0.36), 0.8, OcrRegion.UNKNOWN, "verify"),
                ],
                source_image=str(DATA_DIR / "missing_title.png"),
                engine="verify-ocr",
            ),
            "page": PageClassification(PageType.CHAT_DM, 0.74, "verify chat page with filtered title"),
            "messages": [
                ParsedOcrMessage(
                    Speaker.OTHER,
                    "这条消息不应该入库",
                    _inside(state.layout.message_rect, 0.08, 0.15, 0.42, 0.24),
                    0.88,
                    False,
                    "verify",
                )
            ],
        }
    )
    missing_title = services.ingestion.ingest_pipeline_result(missing_title_result)
    if missing_title.accepted or not missing_title.reason.startswith("contact_title_unavailable:"):
        raise RuntimeError(f"missing title should be rejected with diagnostic reason: {missing_title}")
    if not missing_title.title_candidates or "title:0.91:微信" not in missing_title.reason:
        raise RuntimeError(f"missing title should expose OCR title candidates: {missing_title}")

    group_result = PipelineResult(
        **{
            **result.__dict__,
            "job_id": 3,
            "snapshot_hash": "group",
            "ocr_result": OcrResult(
                boxes=[
                    OcrTextBox("项目推进群（12）", _inside(state.layout.title_rect, 0.05, 0.2, 0.34, 0.72), 0.9, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("今天的方案可以发我吗？", _inside(state.layout.message_rect, 0.08, 0.15, 0.44, 0.24), 0.88, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("我整理后发群里。", _inside(state.layout.message_rect, 0.58, 0.34, 0.92, 0.43), 0.86, OcrRegion.UNKNOWN, "verify"),
                ],
                source_image=str(DATA_DIR / "group.png"),
                engine="verify-ocr",
            ),
            "page": PageClassification(PageType.CHAT_GROUP, 0.74, "verify group page"),
            "messages": [
                ParsedOcrMessage(Speaker.OTHER, "今天的方案可以发我吗？", _inside(state.layout.message_rect, 0.08, 0.15, 0.44, 0.24), 0.88, False, "verify"),
                ParsedOcrMessage(Speaker.ME, "我整理后发群里。", _inside(state.layout.message_rect, 0.58, 0.34, 0.92, 0.43), 0.86, False, "verify"),
            ],
        }
    )
    group_accepted = services.ingestion.ingest_pipeline_result(group_result)
    if not group_accepted.accepted or group_accepted.contact is None:
        raise RuntimeError(f"group ingestion should be accepted: {group_accepted}")
    if group_accepted.contact.conversation_type != ConversationType.GROUP:
        raise RuntimeError(f"group page should create group contact: {group_accepted.contact.conversation_type}")

    messages = services.messages.list_for_contact(accepted.contact.id)
    if len(messages) != 2:
        raise RuntimeError(f"stored message count mismatch: {len(messages)}")

    time_result = PipelineResult(
        **{
            **result.__dict__,
            "job_id": 4,
            "snapshot_hash": "time",
            "ocr_result": OcrResult(
                boxes=[
                    OcrTextBox("时间联系人", _inside(state.layout.title_rect, 0.05, 0.2, 0.28, 0.72), 0.9, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("14:30", _inside(state.layout.message_rect, 0.46, 0.02, 0.56, 0.07), 0.86, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("这是带时间的消息", _inside(state.layout.message_rect, 0.08, 0.15, 0.42, 0.24), 0.88, OcrRegion.UNKNOWN, "verify"),
                    OcrTextBox("输入", _inside(state.layout.input_rect, 0.05, 0.2, 0.16, 0.36), 0.8, OcrRegion.UNKNOWN, "verify"),
                ],
                source_image=str(DATA_DIR / "time.png"),
                engine="verify-ocr",
            ),
            "page": PageClassification(PageType.CHAT_DM, 0.74, "verify timed page"),
            "messages": [],
        }
    )
    from whochat.ocr.parser import parse_visible_messages

    parsed = parse_visible_messages(time_result.ocr_result, time_result.layout)
    time_result = PipelineResult(**{**time_result.__dict__, "messages": parsed})
    time_accepted = services.ingestion.ingest_pipeline_result(time_result)
    if not time_accepted.accepted or time_accepted.contact is None:
        raise RuntimeError(f"time ingestion should be accepted: {time_accepted}")
    timed_messages = services.messages.list_for_contact(time_accepted.contact.id)
    if not timed_messages or timed_messages[0].time_source != "ocr" or timed_messages[0].message_time is None:
        raise RuntimeError(f"expected OCR message time to be stored: {timed_messages}")

    for page_type in [PageType.SETTINGS, PageType.OFFICIAL_ACCOUNT, PageType.NEWS_ARTICLE]:
        non_chat = PipelineResult(
            **{
                **result.__dict__,
                "job_id": 10 + len(page_type.value),
                "snapshot_hash": f"non_chat_{page_type.value}",
                "page": PageClassification(page_type, 0.74, f"verify {page_type.value}"),
                "messages": [
                    ParsedOcrMessage(
                        Speaker.OTHER,
                        f"{page_type.value} should not be stored",
                        _inside(state.layout.message_rect, 0.08, 0.15, 0.44, 0.24),
                        0.88,
                        False,
                        "verify",
                    )
                ],
            }
        )
        blocked_non_chat = services.ingestion.ingest_pipeline_result(non_chat)
        if blocked_non_chat.accepted:
            raise RuntimeError(f"non-chat page should not ingest messages: {blocked_non_chat}")

    print(
        f"accepted={accepted.accepted} contact={accepted.contact.display_name} "
        f"status={accepted.contact.status.value} inserted={accepted.inserted_messages}"
    )
    print(f"duplicate_inserted={duplicate.inserted_messages} duplicate={duplicate.duplicate_messages}")
    print(
        f"blocked={blocked.reason} missing_title={missing_title.reason} "
        f"stored_messages={len(messages)} group={group_accepted.contact.conversation_type.value}"
    )
    return 0


def _inside(rect: Rect, left: float, top: float, right: float, bottom: float) -> Rect:
    return Rect(
        rect.left + round(rect.width * left),
        rect.top + round(rect.height * top),
        rect.left + round(rect.width * right),
        rect.top + round(rect.height * bottom),
    )


if __name__ == "__main__":
    raise SystemExit(main())
