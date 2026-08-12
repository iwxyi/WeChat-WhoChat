from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.core.models import Speaker
from whochat.core.runtime import LayoutRegions, Rect, RegionSource, TargetApp
from whochat.vision.bubbles import detect_bubbles


def main() -> int:
    output = ROOT / "tmp" / "verify" / "dark_theme_bubbles.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (480, 300), (30, 30, 31))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((48, 70, 260, 125), radius=8, fill=(65, 65, 67))
    draw.text((62, 88), "对方消息", fill=(225, 225, 229))
    # Dark WeChat commonly renders the user's accent as #00a361. Keep only a
    # thin text-like mark here so the fixture covers the real failure mode.
    draw.text((350, 170), "我的消息", fill=(0, 163, 97))
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
    if any(item.rect.left < layout.message_rect.left for item in bubbles):
        raise RuntimeError(f"bubble escaped message region: {bubbles}")
    print(f"detected={[(item.speaker.value, item.rect.as_tuple(), item.confidence) for item in bubbles]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
