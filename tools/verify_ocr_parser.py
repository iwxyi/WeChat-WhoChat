from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.core.models import Speaker
from whochat.core.runtime import PageType, Rect, TargetApp
from whochat.ocr.engine import PreviewOcrEngine
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.ocr.parser import classify_page_from_ocr, normalize_ocr_regions, parse_visible_messages
from whochat.platform.adapters import WeChatAdapter
from whochat.platform.window_tracker import WindowInfo


def main() -> int:
    adapter = WeChatAdapter()
    window = adapter.window_snapshot(WindowInfo(hwnd=1, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True))
    layout = adapter.estimate_layout(window)
    if layout is None:
        raise RuntimeError("layout missing")
    if layout.target_app != TargetApp.WECHAT:
        raise RuntimeError(f"expected wechat layout profile, got {layout.target_app}")

    result = OcrResult(
        boxes=[
            OcrTextBox("联系人 A", Rect(430, 16, 520, 44), 0.9, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("下午前能确认吗？", Rect(460, 138, 740, 188), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("我看一下后回复你。", Rect(820, 236, 1138, 286), 0.86, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("输入一些内容", Rect(430, 674, 650, 710), 0.8, OcrRegion.UNKNOWN, "verify"),
        ],
        source_image="verify.png",
        engine="verify",
    )
    normalized = normalize_ocr_regions(result, layout)
    regions = [box.region for box in normalized.boxes]
    if regions.count(OcrRegion.MESSAGE) != 2 or OcrRegion.TITLE not in regions or OcrRegion.INPUT not in regions:
        raise RuntimeError(f"unexpected region assignment: {regions}")

    page = classify_page_from_ocr(result, layout)
    if page.page_type != PageType.CHAT_DM or not page.can_generate_reply:
        raise RuntimeError(f"OCR page classification failed: {page}")

    no_input_result = OcrResult(
        boxes=[
            OcrTextBox("联系人 A", Rect(430, 16, 520, 44), 0.9, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("下午前能确认吗？", Rect(460, 138, 740, 188), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("我看一下后回复你。", Rect(820, 236, 1138, 286), 0.86, OcrRegion.UNKNOWN, "verify"),
        ],
        source_image="verify.png",
        engine="verify",
    )
    no_input_page = classify_page_from_ocr(no_input_result, layout)
    if no_input_page.page_type != PageType.CHAT_DM or not no_input_page.can_generate_reply:
        raise RuntimeError(f"OCR page classification should tolerate empty input area: {no_input_page}")

    messages = parse_visible_messages(result, layout)
    if len(messages) != 2:
        raise RuntimeError(f"expected 2 parsed messages, got {len(messages)}")
    if messages[0].speaker != Speaker.OTHER or messages[1].speaker != Speaker.ME:
        raise RuntimeError(f"speaker inference failed: {[item.speaker for item in messages]}")
    if "rect=" not in messages[1].reason or "center_x=" not in messages[1].reason:
        raise RuntimeError(f"message reason should include coordinate evidence: {messages[1].reason}")

    noisy_result = OcrResult(
        boxes=[
            OcrTextBox("联系人 A", Rect(430, 16, 520, 44), 0.9, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("星期三13:29", Rect(690, 92, 815, 122), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("众48条新消息", Rect(875, 348, 1015, 382), 0.82, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("这个别当成系统提示", Rect(460, 168, 740, 218), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("右侧窄框也应该是我", Rect(900, 254, 1135, 304), 0.86, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("输入一些内容", Rect(430, 674, 650, 710), 0.8, OcrRegion.UNKNOWN, "verify"),
        ],
        source_image="verify.png",
        engine="verify",
    )
    noisy_messages = parse_visible_messages(noisy_result, layout)
    noisy_texts = [item.text for item in noisy_messages]
    if "星期三13:29" in noisy_texts or "众48条新消息" in noisy_texts:
        raise RuntimeError(f"system overlays should not become chat records: {noisy_texts}")
    if len(noisy_messages) != 2:
        raise RuntimeError(f"expected 2 real messages after overlay filtering, got {noisy_messages}")
    if noisy_messages[0].time_text != "星期三13:29":
        raise RuntimeError(f"weekday time anchor was not attached: {noisy_messages[0]}")
    if noisy_messages[1].speaker != Speaker.ME:
        raise RuntimeError(f"right aligned message should be mine: {noisy_messages[1]}")
    if "right_lane=True" not in noisy_messages[1].reason:
        raise RuntimeError(f"right aligned message should expose geometry reason: {noisy_messages[1].reason}")

    message_like_overlay_text = OcrResult(
        boxes=[
            OcrTextBox("联系人 A", Rect(430, 16, 520, 44), 0.9, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("我刚看到48条新消息", Rect(820, 236, 1138, 286), 0.86, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("输入一些内容", Rect(430, 674, 650, 710), 0.8, OcrRegion.UNKNOWN, "verify"),
        ],
        source_image="verify.png",
        engine="verify",
    )
    overlay_text_messages = parse_visible_messages(message_like_overlay_text, layout)
    if [item.text for item in overlay_text_messages] != ["我刚看到48条新消息"]:
        raise RuntimeError(f"normal bubble text should not be filtered by content alone: {overlay_text_messages}")

    group_sender_result = OcrResult(
        boxes=[
            OcrTextBox("项目群(12)", Rect(430, 16, 540, 44), 0.9, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("张三", Rect(462, 132, 508, 153), 0.86, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("今天的方案可以发我吗？", Rect(462, 160, 762, 210), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("收到", Rect(462, 236, 530, 266), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("我整理后发群里。", Rect(840, 330, 1138, 380), 0.86, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("输入一些内容", Rect(430, 674, 650, 710), 0.8, OcrRegion.UNKNOWN, "verify"),
        ],
        source_image="verify.png",
        engine="verify",
    )
    group_messages = parse_visible_messages(group_sender_result, layout)
    if [item.text for item in group_messages] != ["今天的方案可以发我吗？", "收到", "我整理后发群里。"]:
        raise RuntimeError(f"group sender labels should not become messages: {group_messages}")
    if group_messages[0].sender_name != "张三":
        raise RuntimeError(f"group sender label should attach to next message: {group_messages[0]}")
    if group_messages[1].sender_name is not None:
        raise RuntimeError(f"common short reply should not be treated as a sender label: {group_messages[1]}")

    split_bubble_result = OcrResult(
        boxes=[
            OcrTextBox("联系人 A", Rect(430, 16, 520, 44), 0.9, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("今天周三，，我以为今天", Rect(462, 160, 710, 210), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("周五了", Rect(714, 160, 782, 210), 0.86, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("输入一些内容", Rect(430, 674, 650, 710), 0.8, OcrRegion.UNKNOWN, "verify"),
        ],
        source_image="verify.png",
        engine="verify",
    )
    split_messages = parse_visible_messages(split_bubble_result, layout)
    if [item.text for item in split_messages] != ["今天周三，，我以为今天周五了"]:
        raise RuntimeError(f"same bubble OCR fragments should merge into one message: {split_messages}")
    if split_messages[0].speaker != Speaker.OTHER:
        raise RuntimeError(f"merged left bubble should remain OTHER: {split_messages[0]}")

    adapter_page = adapter.classify_page_with_ocr(window, layout, result)
    if adapter_page.page_type != PageType.CHAT_DM:
        raise RuntimeError("adapter did not use OCR page evidence")

    preview = PreviewOcrEngine().recognize(ROOT / "tmp" / "calibration_ui" / "synthetic_wechat.png", layout)
    preview_messages = parse_visible_messages(preview, layout)
    if len(preview_messages) < 2:
        raise RuntimeError("preview engine did not produce message candidates")

    print(f"page={page.page_type.value} confidence={page.confidence:.2f} no_input={no_input_page.confidence:.2f}")
    print(f"messages={[(item.speaker.value, item.text, item.confidence) for item in messages]}")
    print(f"adapter_page={adapter_page.page_type.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
