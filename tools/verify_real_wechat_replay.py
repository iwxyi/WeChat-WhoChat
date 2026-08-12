from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.core.runtime import LayoutRegions, Rect, RegionSource, TargetApp
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox
from whochat.ocr.parser import parse_visible_messages


def main() -> int:
    path = ROOT / "tmp" / "probe" / "wechat_window_ocr.json"
    if not path.exists():
        print("skipped=missing_real_replay_sample")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    layout = _layout(data["layout"])
    result = OcrResult(
        boxes=[
            OcrTextBox(
                str(box["text"]),
                Rect(*(int(item) for item in box["rect"])),
                float(box["confidence"]),
                OcrRegion(str(box["region"])),
                str(box["source"]),
            )
            for box in data["boxes"]
        ],
        source_image=str(data["image"]),
        engine=str(data["engine"]),
        warning=data.get("warning"),
    )
    messages = parse_visible_messages(result, layout)
    texts = [message.text for message in messages]
    if "共4条" in texts:
        raise RuntimeError(f"real WeChat count overlay leaked into messages: {texts!r}")
    if len(messages) < 3:
        raise RuntimeError(f"real WeChat replay unexpectedly lost message candidates: {texts!r}")
    print(f"page={data['page']['type']} messages={len(messages)} count_overlay_filtered=true")
    return 0


def _layout(data: dict) -> LayoutRegions:
    def rect(name: str) -> Rect:
        value = data[name]
        return Rect(int(value["left"]), int(value["top"]), int(value["right"]), int(value["bottom"]))

    return LayoutRegions(
        target_app=TargetApp(str(data.get("target_app", TargetApp.WECHAT.value))),
        bubble_profile=str(data.get("bubble_profile", "wechat_green")),
        window_rect=rect("window_rect"),
        nav_rect=rect("nav_rect"),
        chat_list_rect=rect("chat_list_rect"),
        content_rect=rect("content_rect"),
        title_rect=rect("title_rect"),
        message_rect=rect("message_rect"),
        input_rect=rect("input_rect"),
        confidence=float(data["confidence"]),
        source=RegionSource(str(data["source"])),
        reason=str(data["reason"]),
    )


if __name__ == "__main__":
    raise SystemExit(main())
