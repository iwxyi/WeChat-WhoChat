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
    stable_message_boxes = [box for box in message_boxes if not _is_edge_partial_box(box, layout)]
    input_boxes = [box for box in normalized.boxes if box.region == OcrRegion.INPUT and box.confidence >= 0.4]
    title_boxes = [box for box in normalized.boxes if box.region == OcrRegion.TITLE and box.confidence >= 0.45]
    chat_list_boxes = [box for box in normalized.boxes if box.region == OcrRegion.CHAT_LIST and box.confidence >= 0.4]

    non_chat = _classify_non_chat_page(title_boxes, message_boxes, input_boxes)
    if non_chat is not None:
        return non_chat

    group_title = any(_looks_like_group_title(box.text) for box in title_boxes)
    if len(stable_message_boxes) >= 2 and input_boxes and title_boxes:
        confidence = min(0.78, 0.55 + len(stable_message_boxes) * 0.06 + len(input_boxes) * 0.04)
        page_type = PageType.CHAT_GROUP if group_title else PageType.CHAT_DM
        return PageClassification(
            page_type,
            confidence,
            f"OCR 证据包含标题、输入区和 {len(stable_message_boxes)} 个稳定消息候选"
            + ("；标题呈现群聊特征" if group_title else ""),
        )
    if len(stable_message_boxes) >= 2 and title_boxes:
        confidence = min(0.72, 0.54 + len(stable_message_boxes) * 0.05 + len(title_boxes) * 0.03)
        page_type = PageType.CHAT_GROUP if group_title else PageType.CHAT_DM
        return PageClassification(
            page_type,
            confidence,
            f"OCR 证据包含标题和 {len(stable_message_boxes)} 个稳定消息候选；输入区未识别到文字但不阻断聊天页判断"
            + ("；标题呈现群聊特征" if group_title else ""),
        )
    if len(stable_message_boxes) >= 3 and input_boxes:
        return PageClassification(
            PageType.CHAT_DM,
            0.67,
            f"OCR 证据包含输入区和 {len(stable_message_boxes)} 个稳定消息候选；标题漏检，按私聊候选处理",
        )
    if len(stable_message_boxes) >= 2 and (input_boxes or title_boxes):
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
    if (
        not message_boxes
        and _contains_any(combined, ("搜索指定内容", "搜索聊天记录", "联系人", "群聊", "聊天记录"))
        and not input_boxes
    ):
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
    sender_labels = _assign_sender_labels(message_boxes, layout, timeline["anchors"])
    filtered = [
        box for box in message_boxes
        if box not in timeline["anchors"]
        and box not in sender_labels["labels"]
        and not _looks_like_non_message_overlay(box, layout)
    ]
    merged = _merge_message_fragments(filtered, layout)
    return [
        _message_from_box(box, layout, timeline["times"].get(box), sender_labels["senders"].get(box))
        for box in merged
    ]


def _merge_message_fragments(boxes: list[OcrTextBox], layout: LayoutRegions) -> list[OcrTextBox]:
    if len(boxes) < 2:
        return boxes
    ordered = sorted(boxes, key=lambda box: (box.rect.top, box.rect.left))
    merged: list[OcrTextBox] = []
    current = ordered[0]
    for box in ordered[1:]:
        if _should_merge_fragments(current, box, layout):
            current = _merge_boxes(current, box)
        else:
            merged.append(current)
            current = box
    merged.append(current)
    return merged


def _should_merge_fragments(left: OcrTextBox, right: OcrTextBox, layout: LayoutRegions) -> bool:
    left_speaker, _left_reason = _speaker_from_geometry(left, layout)
    right_speaker, _right_reason = _speaker_from_geometry(right, layout)
    if left_speaker != right_speaker:
        return False
    if _is_edge_partial_box(left, layout) or _is_edge_partial_box(right, layout):
        return False
    if _looks_like_non_message_overlay(left, layout) or _looks_like_non_message_overlay(right, layout):
        return False
    same_row = _vertical_overlap_ratio(left.rect, right.rect) >= 0.45
    close_rows = abs(right.rect.top - left.rect.bottom) <= max(10, round(layout.message_rect.height * 0.025))
    horizontal_gap = right.rect.left - left.rect.right
    adjacent_horizontal = -max(8, round(layout.message_rect.width * 0.015)) <= horizontal_gap <= max(56, round(layout.message_rect.width * 0.09))
    aligned_left = abs(left.rect.left - right.rect.left) <= max(30, round(layout.message_rect.width * 0.05))
    close_vertical = 0 <= right.rect.top - left.rect.bottom <= max(18, round(layout.message_rect.height * 0.035))
    same_bubble_width = _merged_width(left.rect, right.rect) <= layout.message_rect.width * 0.72
    if same_row and adjacent_horizontal and same_bubble_width:
        return True
    return close_rows and close_vertical and aligned_left and same_bubble_width


def _merge_boxes(left: OcrTextBox, right: OcrTextBox) -> OcrTextBox:
    same_row = _vertical_overlap_ratio(left.rect, right.rect) >= 0.45
    separator = "" if same_row else "\n"
    rect = Rect(
        min(left.rect.left, right.rect.left),
        min(left.rect.top, right.rect.top),
        max(left.rect.right, right.rect.right),
        max(left.rect.bottom, right.rect.bottom),
    )
    confidence = min(left.confidence, right.confidence)
    return OcrTextBox(
        text=f"{left.text.strip()}{separator}{right.text.strip()}",
        rect=rect,
        confidence=confidence,
        region=left.region,
        source=left.source,
    )


def _vertical_overlap_ratio(left: Rect, right: Rect) -> float:
    overlap = max(0, min(left.bottom, right.bottom) - max(left.top, right.top))
    return overlap / max(1, min(left.height, right.height))


def _merged_width(left: Rect, right: Rect) -> int:
    return max(left.right, right.right) - min(left.left, right.left)


def _message_from_box(
    box: OcrTextBox,
    layout: LayoutRegions,
    time_text: str | None = None,
    sender_name: str | None = None,
) -> ParsedOcrMessage:
    speaker, geometry_reason = _speaker_from_geometry(box, layout)
    partial = _is_edge_partial_box(box, layout)
    confidence = min(0.95, max(0.0, box.confidence - (0.08 if partial else 0.0)))
    reason = f"根据消息区坐标推断说话人：{geometry_reason}"
    if sender_name:
        reason += f"；上方坐标标签识别为发送者：{sender_name}"
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
        sender_name=sender_name,
    )


def _is_edge_partial_box(box: OcrTextBox, layout: LayoutRegions) -> bool:
    edge_margin = max(8, round(layout.message_rect.height * 0.025))
    return box.rect.top <= layout.message_rect.top + edge_margin or box.rect.bottom >= layout.message_rect.bottom - edge_margin


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


def _assign_sender_labels(
    boxes: list[OcrTextBox],
    layout: LayoutRegions,
    ignored: set[OcrTextBox],
) -> dict[str, object]:
    labels: set[OcrTextBox] = set()
    senders: dict[OcrTextBox, str] = {}
    usable = [box for box in boxes if box not in ignored and not _looks_like_non_message_overlay(box, layout)]
    for index, box in enumerate(usable):
        next_box = _next_lower_left_message_box(box, usable[index + 1 :], layout)
        if _looks_like_sender_label(box, next_box, layout):
            labels.add(box)
            senders[next_box] = box.text.strip()
    return {"labels": labels, "senders": senders}


def _next_lower_left_message_box(
    box: OcrTextBox,
    candidates: list[OcrTextBox],
    layout: LayoutRegions,
) -> OcrTextBox | None:
    max_gap = max(22, round(layout.message_rect.height * 0.045))
    for candidate in candidates:
        if candidate.rect.top < box.rect.bottom:
            continue
        if candidate.rect.top - box.rect.bottom > max_gap:
            return None
        if _is_left_bubble_lane(candidate, layout):
            return candidate
    return None


def _looks_like_sender_label(box: OcrTextBox, next_box: OcrTextBox | None, layout: LayoutRegions) -> bool:
    text = box.text.strip()
    if next_box is None or not text:
        return False
    if not _looks_like_sender_label_text(text):
        return False
    if not _is_left_label_lane(box, layout):
        return False
    vertical_gap = next_box.rect.top - box.rect.bottom
    horizontal_gap = abs(next_box.rect.left - box.rect.left)
    aligned_with_next = horizontal_gap <= max(42, round(layout.message_rect.width * 0.07))
    compact_label = box.rect.height <= max(24, round(layout.message_rect.height * 0.045))
    narrower_than_message = box.rect.width <= max(150, round(next_box.rect.width * 0.72))
    return 0 <= vertical_gap <= max(22, round(layout.message_rect.height * 0.045)) and aligned_with_next and compact_label and narrower_than_message


def _looks_like_sender_label_text(text: str) -> bool:
    value = text.strip()
    if len(value) > 16:
        return False
    if any(ch in value for ch in "，。！？,.?!:：；;、"):
        return False
    if _looks_like_time_text(value) or _looks_like_new_message_text(_compact_text(value)):
        return False
    common_short_messages = {
        "好",
        "好的",
        "收到",
        "可以",
        "行",
        "嗯",
        "嗯嗯",
        "OK",
        "ok",
        "谢谢",
        "辛苦了",
    }
    return value not in common_short_messages


def _looks_like_non_message_overlay(box: OcrTextBox, layout: LayoutRegions) -> bool:
    text = _compact_text(box.text)
    if not text:
        return True
    if _looks_like_new_message_text(text) and _is_floating_new_message_hint(box, layout):
        return True
    if _is_center_system_hint(box, layout) and _looks_like_time_text(text):
        return True
    return False


def _looks_like_new_message_text(text: str) -> bool:
    return bool(
        re.match(r"^[↑⬆上个]?\d{1,4}条新消息$", text)
        or re.match(r"^[^\d]{0,2}\d{1,4}条新消息$", text)
    )


def _speaker_from_geometry(box: OcrTextBox, layout: LayoutRegions) -> tuple[Speaker, str]:
    center_ratio = _horizontal_ratio(box, layout)
    left_ratio = _edge_ratio(box.rect.left, layout)
    right_ratio = _edge_ratio(box.rect.right, layout)
    left_aligned = _is_left_bubble_lane(box, layout)
    right_aligned = _is_right_bubble_lane(box, layout)
    speaker = Speaker.ME if center_ratio >= 0.54 or (right_aligned and not left_aligned) else Speaker.OTHER
    reason = (
        f"rect={box.rect.as_tuple()} center_x={center_ratio:.2f} "
        f"left={left_ratio:.2f} right={right_ratio:.2f} "
        f"left_lane={left_aligned} right_lane={right_aligned}"
    )
    return speaker, reason


def _is_left_bubble_lane(box: OcrTextBox, layout: LayoutRegions) -> bool:
    left_ratio = _edge_ratio(box.rect.left, layout)
    center_ratio = _horizontal_ratio(box, layout)
    return left_ratio <= 0.22 and center_ratio <= 0.62


def _is_left_label_lane(box: OcrTextBox, layout: LayoutRegions) -> bool:
    left_ratio = _edge_ratio(box.rect.left, layout)
    center_ratio = _horizontal_ratio(box, layout)
    return left_ratio <= 0.26 and center_ratio <= 0.50


def _is_right_bubble_lane(box: OcrTextBox, layout: LayoutRegions) -> bool:
    right_ratio = _edge_ratio(box.rect.right, layout)
    center_ratio = _horizontal_ratio(box, layout)
    return right_ratio >= 0.90 and center_ratio >= 0.48


def _is_center_system_hint(box: OcrTextBox, layout: LayoutRegions) -> bool:
    center_ratio = _horizontal_ratio(box, layout)
    narrow = box.rect.width <= layout.message_rect.width * 0.36
    return narrow and 0.38 <= center_ratio <= 0.62


def _is_floating_new_message_hint(box: OcrTextBox, layout: LayoutRegions) -> bool:
    center_ratio = _horizontal_ratio(box, layout)
    width_ratio = box.rect.width / max(1, layout.message_rect.width)
    height_ratio = box.rect.height / max(1, layout.message_rect.height)
    if _is_left_bubble_lane(box, layout) or _is_right_bubble_lane(box, layout):
        return False
    return 0.55 <= center_ratio <= 0.90 and width_ratio <= 0.34 and height_ratio <= 0.11


def _horizontal_ratio(box: OcrTextBox, layout: LayoutRegions) -> float:
    center_x = (box.rect.left + box.rect.right) / 2
    return _edge_ratio(center_x, layout)


def _edge_ratio(value: float, layout: LayoutRegions) -> float:
    return (value - layout.message_rect.left) / max(1, layout.message_rect.width)


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
    text = _compact_text(box.text)
    if not text or len(text) > 24:
        return False
    center_x = (box.rect.left + box.rect.right) / 2
    middle = layout.message_rect.left + layout.message_rect.width / 2
    if abs(center_x - middle) > layout.message_rect.width * 0.18:
        return False
    return _looks_like_time_text(text)


def _looks_like_time_text(text: str) -> bool:
    value = _compact_text(text)
    patterns = [
        r"^\d{1,2}:\d{2}$",
        r"^(上午|下午|晚上|中午|凌晨)?\d{1,2}:\d{2}$",
        r"^(昨天|今天|周[一二三四五六日天]|星期[一二三四五六日天])(上午|下午|晚上|中午|凌晨)?\d{1,2}:\d{2}$",
        r"^\d{1,2}月\d{1,2}日(上午|下午|晚上|中午|凌晨)?\d{1,2}:\d{2}$",
        r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}(上午|下午|晚上|中午|凌晨)?\d{1,2}:\d{2}$",
    ]
    return any(re.match(pattern, value) for pattern in patterns)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text.strip())
