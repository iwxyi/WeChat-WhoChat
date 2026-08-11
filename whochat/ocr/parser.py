from __future__ import annotations

import re
from dataclasses import replace

from whochat.core.models import Speaker
from whochat.core.runtime import LayoutRegions, PageClassification, PageType, Rect
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox, ParsedOcrMessage


def normalize_ocr_regions(result: OcrResult, layout: LayoutRegions) -> OcrResult:
    boxes = [replace(box, region=classify_box_region(box.rect, layout)) for box in result.boxes]
    return OcrResult(boxes=boxes, source_image=result.source_image, engine=result.engine, warning=result.warning)


def classify_box_region(rect: Rect, layout: LayoutRegions) -> OcrRegion:
    candidates = [
        (OcrRegion.TITLE, _overlap_ratio(rect, layout.title_rect)),
        (OcrRegion.CHAT_LIST, _overlap_ratio(rect, layout.chat_list_rect)),
        (OcrRegion.MESSAGE, _overlap_ratio(rect, layout.message_rect)),
        (OcrRegion.INPUT, _overlap_ratio(rect, layout.input_rect)),
    ]
    region, score = max(candidates, key=lambda item: item[1])
    return region if score >= 0.35 else OcrRegion.UNKNOWN


def classify_page_from_ocr(result: OcrResult, layout: LayoutRegions) -> PageClassification:
    normalized = normalize_ocr_regions(result, layout)
    message_boxes = [box for box in normalized.boxes if box.region == OcrRegion.MESSAGE and box.confidence >= 0.45]
    input_boxes = [box for box in normalized.boxes if box.region == OcrRegion.INPUT and box.confidence >= 0.4]
    title_boxes = [box for box in normalized.boxes if box.region == OcrRegion.TITLE and box.confidence >= 0.45]
    chat_list_boxes = [box for box in normalized.boxes if box.region == OcrRegion.CHAT_LIST and box.confidence >= 0.4]

    non_chat = _classify_non_chat_page(title_boxes, message_boxes, input_boxes)
    if non_chat is not None:
        return non_chat

    group_title = any(_looks_like_group_title(box.text) for box in title_boxes)
    if len(message_boxes) >= 2 and input_boxes and title_boxes:
        confidence = min(0.78, 0.55 + len(message_boxes) * 0.06 + len(input_boxes) * 0.04)
        page_type = PageType.CHAT_GROUP if group_title else PageType.CHAT_DM
        return PageClassification(
            page_type,
            confidence,
            f"OCR 证据包含标题、输入区和 {len(message_boxes)} 个消息候选"
            + ("；标题呈现群聊特征" if group_title else ""),
        )
    if len(message_boxes) >= 2 and (input_boxes or title_boxes):
        return PageClassification(
            PageType.UNKNOWN,
            0.58,
            "OCR 看到消息结构，但标题或输入区证据不足，暂不允许 AI",
        )
    if chat_list_boxes and not message_boxes:
        return PageClassification(
            PageType.SEARCH,
            0.46,
            "OCR 主要落在左侧列表，右侧聊天结构不足",
        )
    return PageClassification(PageType.UNKNOWN, 0.35, "OCR 证据不足，保持未知页面")


def _classify_non_chat_page(
    title_boxes: list[OcrTextBox],
    message_boxes: list[OcrTextBox],
    input_boxes: list[OcrTextBox],
) -> PageClassification | None:
    title_text = " ".join(box.text.strip() for box in title_boxes if box.text.strip())
    body_text = " ".join(box.text.strip() for box in message_boxes if box.text.strip())
    input_text = " ".join(box.text.strip() for box in input_boxes if box.text.strip())
    combined = " ".join([title_text, body_text, input_text])
    if not combined:
        return None
    if _contains_any(title_text, ("设置", "通用", "账号与安全", "消息通知", "隐私", "关于微信")):
        return PageClassification(PageType.SETTINGS, 0.74, "OCR 标题呈现设置页特征，阻断聊天回复")
    if _contains_any(title_text, ("订阅号", "公众号", "服务号")) or _contains_any(body_text, ("关注公众号", "进入公众号", "服务通知")):
        return PageClassification(PageType.OFFICIAL_ACCOUNT, 0.72, "OCR 呈现公众号或服务号特征，阻断聊天回复")
    article_markers = ("阅读全文", "原文链接", "作者", "发布于", "阅读量", "赞", "在看", "分享")
    if len(body_text) >= 80 and _contains_any(body_text, article_markers):
        return PageClassification(PageType.NEWS_ARTICLE, 0.70, "OCR 呈现文章页正文和操作特征，阻断聊天回复")
    if _contains_any(combined, ("搜索指定内容", "搜索聊天记录", "联系人", "群聊", "聊天记录")) and not input_boxes:
        return PageClassification(PageType.SEARCH, 0.60, "OCR 呈现搜索或列表页特征，阻断聊天回复")
    return None


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def parse_visible_messages(result: OcrResult, layout: LayoutRegions) -> list[ParsedOcrMessage]:
    normalized = normalize_ocr_regions(result, layout)
    message_boxes = [
        box for box in normalized.boxes
        if box.region == OcrRegion.MESSAGE and box.text.strip() and box.confidence >= 0.35
    ]
    message_boxes.sort(key=lambda box: (box.rect.top, box.rect.left))
    timeline = _assign_time_anchors(message_boxes, layout)
    filtered = [
        box for index, box in enumerate(message_boxes)
        if box not in timeline["anchors"]
        and not _looks_like_sender_label(box, message_boxes[index + 1] if index + 1 < len(message_boxes) else None, layout)
    ]
    return [_message_from_box(box, layout, timeline["times"].get(box)) for box in filtered]


def _message_from_box(box: OcrTextBox, layout: LayoutRegions, time_text: str | None = None) -> ParsedOcrMessage:
    center_x = (box.rect.left + box.rect.right) / 2
    midpoint = layout.message_rect.left + layout.message_rect.width * 0.54
    speaker = Speaker.ME if center_x >= midpoint else Speaker.OTHER
    edge_margin = max(8, round(layout.message_rect.height * 0.025))
    partial = box.rect.top <= layout.message_rect.top + edge_margin or box.rect.bottom >= layout.message_rect.bottom - edge_margin
    confidence = min(0.95, max(0.0, box.confidence - (0.08 if partial else 0.0)))
    reason = "根据消息区水平位置推断说话人"
    if partial:
        reason += "；文本接近消息区边缘，标记为 partial"
    return ParsedOcrMessage(
        speaker=speaker,
        text=box.text.strip(),
        rect=box.rect,
        confidence=confidence,
        partial=partial,
        reason=reason,
        time_text=time_text,
    )


def _overlap_ratio(left: Rect, right: Rect) -> float:
    overlap_left = max(left.left, right.left)
    overlap_top = max(left.top, right.top)
    overlap_right = min(left.right, right.right)
    overlap_bottom = min(left.bottom, right.bottom)
    overlap_width = max(0, overlap_right - overlap_left)
    overlap_height = max(0, overlap_bottom - overlap_top)
    overlap_area = overlap_width * overlap_height
    area = max(1, left.width * left.height)
    return overlap_area / area


def _looks_like_group_title(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if re.search(r"[（(]\s*\d{2,}\s*[)）]", text):
        return True
    markers = ("群", "班级", "项目组", "交流群", "讨论组")
    return any(marker in text for marker in markers)


def _looks_like_sender_label(box: OcrTextBox, next_box: OcrTextBox | None, layout: LayoutRegions) -> bool:
    text = box.text.strip()
    if next_box is None or not text:
        return False
    if len(text) > 10 or any(ch in text for ch in "，。！？,.?!:："):
        return False
    center_x = (box.rect.left + box.rect.right) / 2
    midpoint = layout.message_rect.left + layout.message_rect.width * 0.54
    if center_x >= midpoint:
        return False
    vertical_gap = next_box.rect.top - box.rect.bottom
    left_aligned = abs(next_box.rect.left - box.rect.left) <= max(24, round(layout.message_rect.width * 0.04))
    compact_label = box.rect.height <= max(26, round(layout.message_rect.height * 0.06))
    return 0 <= vertical_gap <= 18 and left_aligned and compact_label


def _assign_time_anchors(boxes: list[OcrTextBox], layout: LayoutRegions) -> dict[str, object]:
    anchors: set[OcrTextBox] = set()
    times: dict[OcrTextBox, str] = {}
    current: str | None = None
    for box in boxes:
        if _looks_like_time_anchor(box, layout):
            anchors.add(box)
            current = box.text.strip()
            continue
        if current:
            times[box] = current
    return {"anchors": anchors, "times": times}


def _looks_like_time_anchor(box: OcrTextBox, layout: LayoutRegions) -> bool:
    text = box.text.strip()
    if not text or len(text) > 24:
        return False
    center_x = (box.rect.left + box.rect.right) / 2
    middle = layout.message_rect.left + layout.message_rect.width / 2
    if abs(center_x - middle) > layout.message_rect.width * 0.18:
        return False
    patterns = [
        r"^\d{1,2}:\d{2}$",
        r"^(上午|下午|晚上|中午|凌晨)?\s*\d{1,2}:\d{2}$",
        r"^(昨天|今天)\s*(上午|下午|晚上|中午|凌晨)?\s*\d{1,2}:\d{2}$",
        r"^\d{1,2}月\d{1,2}日\s*(上午|下午|晚上|中午|凌晨)?\s*\d{1,2}:\d{2}$",
        r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}\s*(上午|下午|晚上|中午|凌晨)?\s*\d{1,2}:\d{2}$",
    ]
    return any(re.match(pattern, text) for pattern in patterns)
