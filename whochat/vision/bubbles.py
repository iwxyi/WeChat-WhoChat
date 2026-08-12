from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from whochat.core.models import Speaker
from whochat.core.runtime import LayoutRegions, Rect, TargetApp


@dataclass(frozen=True)
class BubbleRegion:
    rect: Rect
    speaker: Speaker
    confidence: float
    partial: bool
    profile: str


def detect_bubbles(image_path: str | Path, layout: LayoutRegions) -> list[BubbleRegion]:
    profile = bubble_profile_for_layout(layout)
    if profile == "wechat_green":
        return _detect_wechat_green_bubbles(Path(image_path), layout)
    return []


def bubble_profile_for_layout(layout: LayoutRegions) -> str:
    if layout.bubble_profile and layout.bubble_profile != "auto":
        return layout.bubble_profile
    if layout.target_app == TargetApp.WECHAT:
        return "wechat_green"
    return "geometry"


def bubble_for_box(box: Rect, bubbles: list[BubbleRegion]) -> BubbleRegion | None:
    if not bubbles:
        return None
    center_x = (box.left + box.right) // 2
    center_y = (box.top + box.bottom) // 2
    containing = [
        bubble
        for bubble in bubbles
        if bubble.rect.left <= center_x <= bubble.rect.right and bubble.rect.top <= center_y <= bubble.rect.bottom
    ]
    if containing:
        return max(containing, key=lambda bubble: bubble.confidence)
    overlaps = [(bubble, _overlap_ratio(box, bubble.rect)) for bubble in bubbles]
    bubble, score = max(overlaps, key=lambda item: item[1])
    return bubble if score >= 0.25 else None


def _detect_wechat_green_bubbles(image_path: Path, layout: LayoutRegions) -> list[BubbleRegion]:
    if not image_path.exists():
        return []
    try:
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            crop = rgb.crop(layout.message_rect.as_tuple())
    except OSError:
        return []
    width, height = crop.size
    if width < 80 or height < 80:
        return []
    # Text and thin outlines in WeChat's dark theme are often the only green
    # pixels left; dilate them slightly before finding message-level regions.
    mask = _dilate_mask(_green_mask(crop), width, height)
    components = _group_green_components(_connected_components(mask, width, height), width, height)
    bubbles: list[BubbleRegion] = []
    min_area = max(48, round(width * height * 0.00018))
    for left, top, right, bottom, area in components:
        rect = Rect(
            layout.message_rect.left + left,
            layout.message_rect.top + top,
            layout.message_rect.left + right,
            layout.message_rect.top + bottom,
        )
        if area < min_area or rect.width < 18 or rect.height < 8:
            continue
        center_ratio = ((rect.left + rect.right) / 2 - layout.message_rect.left) / max(1, layout.message_rect.width)
        if center_ratio < 0.45:
            continue
        density = area / max(1, rect.width * rect.height)
        partial = rect.top <= layout.message_rect.top + 4 or rect.bottom >= layout.message_rect.bottom - 4
        confidence = min(0.95, 0.58 + density * 0.5 + max(0.0, center_ratio - 0.55) * 0.35)
        bubbles.append(BubbleRegion(rect, Speaker.ME, confidence, partial, "wechat_green"))
    bubbles.sort(key=lambda bubble: (bubble.rect.top, bubble.rect.left))
    return _merge_close_bubbles(bubbles, layout)


def _green_mask(image: Image.Image) -> list[bool]:
    pixels = list(image.getdata())
    mask: list[bool] = []
    for red, green, blue in pixels:
        # The dark theme's accent is commonly close to #00a361.  Do not
        # require a non-zero red channel: that was the reason real screenshots
        # produced no detections.
        light_wechat = green >= 125 and red <= 220 and blue <= 205 and green - red >= 18 and green - blue >= 18
        dark_wechat = green >= 80 and red <= 150 and blue <= 175 and green - red >= 20 and green - blue >= 15
        mask.append(light_wechat or dark_wechat)
    return mask


def _dilate_mask(mask: list[bool], width: int, height: int) -> list[bool]:
    expanded = bytearray(len(mask))
    for index, value in enumerate(mask):
        if not value:
            continue
        x = index % width
        y = index // width
        for dy in (-1, 0, 1):
            next_y = y + dy
            if next_y < 0 or next_y >= height:
                continue
            for dx in (-1, 0, 1):
                next_x = x + dx
                if 0 <= next_x < width:
                    expanded[next_y * width + next_x] = 1
    return [bool(value) for value in expanded]


def _connected_components(mask: list[bool], width: int, height: int) -> list[tuple[int, int, int, int, int]]:
    seen = bytearray(width * height)
    components: list[tuple[int, int, int, int, int]] = []
    for index, value in enumerate(mask):
        if not value or seen[index]:
            continue
        stack = [index]
        seen[index] = 1
        left = right = index % width
        top = bottom = index // width
        area = 0
        while stack:
            current = stack.pop()
            area += 1
            x = current % width
            y = current // width
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)
            for neighbor in _neighbors(x, y, width, height):
                if mask[neighbor] and not seen[neighbor]:
                    seen[neighbor] = 1
                    stack.append(neighbor)
        components.append((left, top, right + 1, bottom + 1, area))
    return components


def _group_green_components(
    components: list[tuple[int, int, int, int, int]], width: int, height: int
) -> list[tuple[int, int, int, int, int]]:
    """Join anti-aliased characters/edges into a message-level green region."""
    pending = sorted(components, key=lambda item: (item[1], item[0]))
    grouped: list[tuple[int, int, int, int, int]] = []
    max_gap = max(12, round(height * 0.045))
    max_horizontal_gap = max(24, round(width * 0.06))
    for component in pending:
        if not grouped:
            grouped.append(component)
            continue
        previous = grouped[-1]
        left, top, right, bottom, area = component
        p_left, p_top, p_right, p_bottom, p_area = previous
        vertical_gap = max(0, max(p_top, top) - min(p_bottom, bottom))
        horizontal_gap = max(0, max(p_left, left) - min(p_right, right))
        vertical_overlap = min(p_bottom, bottom) - max(p_top, top)
        close_on_same_message = (
            vertical_gap <= max_gap
            and horizontal_gap <= max_horizontal_gap
            and (vertical_overlap > 0 or abs(top - p_top) <= max_gap)
            and max(right, p_right) - min(left, p_left) <= round(width * 0.78)
        )
        if close_on_same_message:
            grouped[-1] = (
                min(p_left, left),
                min(p_top, top),
                max(p_right, right),
                max(p_bottom, bottom),
                p_area + area,
            )
        else:
            grouped.append(component)
    return grouped


def _neighbors(x: int, y: int, width: int, height: int):
    if x > 0:
        yield y * width + x - 1
    if x + 1 < width:
        yield y * width + x + 1
    if y > 0:
        yield (y - 1) * width + x
    if y + 1 < height:
        yield (y + 1) * width + x


def _merge_close_bubbles(bubbles: list[BubbleRegion], layout: LayoutRegions) -> list[BubbleRegion]:
    if len(bubbles) < 2:
        return bubbles
    merged: list[BubbleRegion] = []
    current = bubbles[0]
    for bubble in bubbles[1:]:
        vertical_gap = bubble.rect.top - current.rect.bottom
        horizontal_overlap = min(current.rect.right, bubble.rect.right) - max(current.rect.left, bubble.rect.left)
        if 0 <= vertical_gap <= max(5, round(layout.message_rect.height * 0.012)) and horizontal_overlap > 0:
            rect = Rect(
                min(current.rect.left, bubble.rect.left),
                min(current.rect.top, bubble.rect.top),
                max(current.rect.right, bubble.rect.right),
                max(current.rect.bottom, bubble.rect.bottom),
            )
            current = BubbleRegion(
                rect=rect,
                speaker=current.speaker,
                confidence=max(current.confidence, bubble.confidence),
                partial=current.partial or bubble.partial,
                profile=current.profile,
            )
        else:
            merged.append(current)
            current = bubble
    merged.append(current)
    return merged


def _overlap_ratio(left: Rect, right: Rect) -> float:
    overlap_left = max(left.left, right.left)
    overlap_top = max(left.top, right.top)
    overlap_right = min(left.right, right.right)
    overlap_bottom = min(left.bottom, right.bottom)
    area = max(0, overlap_right - overlap_left) * max(0, overlap_bottom - overlap_top)
    return area / max(1, left.width * left.height)
