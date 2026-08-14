from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.core.models import Speaker
from whochat.core.runtime import LayoutRegions, Rect, RegionSource, TargetApp
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.ocr.parser import parse_visible_messages
from whochat.vision.bubbles import detect_bubbles


def main() -> int:
    output = ROOT / "tmp" / "verify" / "dark_theme_bubbles.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (480, 300), (30, 30, 31))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((248, 70, 430, 125), radius=8, fill=(65, 65, 67))
    draw.text((262, 88), "对方消息", fill=(225, 225, 229))
    draw.text((262, 136), "张三", fill=(210, 210, 214))
    draw.rounded_rectangle((248, 160, 388, 210), radius=8, fill=(65, 65, 67))
    draw.text((262, 176), "收到", fill=(225, 225, 229))
    # Dark WeChat commonly renders the user's accent as #00a361. Keep only a
    # thin text-like mark here so the fixture covers the real failure mode.
    draw.text((420, 224), "我的消息", fill=(0, 163, 97))
    # A clipped message at the top edge must remain marked partial.
    draw.text((350, 44), "顶部截断", fill=(0, 163, 97))
    image.save(output)

    layout = LayoutRegions(
        target_app=TargetApp.WECHAT,
        bubble_profile="wechat_green",
        window_rect=Rect(0, 0, 480, 300),
        nav_rect=Rect(0, 0, 50, 300),
        chat_list_rect=Rect(50, 0, 200, 300),
        content_rect=Rect(200, 0, 480, 300),
        title_rect=Rect(200, 0, 480, 45),
        message_rect=Rect(200, 45, 480, 260),
        input_rect=Rect(200, 260, 480, 300),
        confidence=0.9,
        source=RegionSource.CALIBRATED,
        reason="fixture",
    )
    bubbles = detect_bubbles(output, layout)
    if not bubbles:
        raise RuntimeError("dark-theme green message was not detected")
    if all(item.speaker != Speaker.ME for item in bubbles):
        raise RuntimeError(f"green evidence was not classified as ME: {bubbles}")
    if all(item.speaker != Speaker.OTHER for item in bubbles):
        raise RuntimeError(f"left gray evidence was not classified as OTHER: {bubbles}")
    if any(item.rect.left < layout.message_rect.left for item in bubbles):
        raise RuntimeError(f"bubble escaped message region: {bubbles}")
    parsed = parse_visible_messages(
        OcrResult(
            boxes=[
                OcrTextBox("联系人", Rect(220, 10, 270, 30), 0.9, OcrRegion.TITLE, "fixture"),
                OcrTextBox("对方消息", Rect(260, 88, 318, 105), 0.9, OcrRegion.MESSAGE, "fixture"),
                OcrTextBox("张三", Rect(260, 136, 292, 153), 0.9, OcrRegion.MESSAGE, "fixture"),
                OcrTextBox("收到", Rect(260, 176, 292, 193), 0.9, OcrRegion.MESSAGE, "fixture"),
                OcrTextBox("我的消息", Rect(420, 224, 448, 241), 0.9, OcrRegion.MESSAGE, "fixture"),
                OcrTextBox("顶部截断", Rect(348, 45, 382, 60), 0.9, OcrRegion.MESSAGE, "fixture"),
            ],
            source_image=str(output),
            engine="fixture",
        ),
        layout,
    )
    if [item.text for item in parsed] != ["顶部截断", "对方消息", "收到", "我的消息"]:
        raise RuntimeError(f"parser did not separate sender labels and messages: {parsed}")
    if parsed[1].speaker != Speaker.OTHER or parsed[2].speaker != Speaker.OTHER or parsed[3].speaker != Speaker.ME:
        raise RuntimeError(f"parser did not use visual speaker evidence: {parsed}")
    if parsed[2].sender_name != "张三":
        raise RuntimeError(f"sender label did not attach to left bubble: {parsed}")
    if not any(item.partial for item in parsed):
        raise RuntimeError(f"edge bubble was not marked partial: {parsed}")
    if not any("气泡=wechat_left/other" in item.reason for item in parsed):
        raise RuntimeError(f"parser reason lacks left bubble evidence: {parsed}")
    if not any("气泡=wechat_green/me" in item.reason for item in parsed):
        raise RuntimeError(f"parser reason lacks bubble evidence: {parsed}")
    print(f"detected={[(item.speaker.value, item.rect.as_tuple(), item.confidence) for item in bubbles]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
