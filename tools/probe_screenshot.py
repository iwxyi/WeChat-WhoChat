from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.capture.screenshot import capture_rect
from whochat.platform.window_tracker import find_wechat_windows


def main() -> int:
    out_dir = ROOT / "tmp" / "probe"
    windows = find_wechat_windows()
    source = "screen_sample"
    rect = (0, 0, 640, 360)
    output = out_dir / "screen_sample.png"
    if windows:
        capturable = [item for item in windows if item.visible and item.foreground]
        if not capturable:
            window = max(windows, key=lambda item: (item.rect[2] - item.rect[0]) * (item.rect[3] - item.rect[1]))
            print(f"status=blocked source=wechat title={window.title!r} rect={window.rect}")
            print(f"reason={window.diagnostic or 'target window is not capturable'}")
            return 0
        window = max(capturable, key=lambda item: (item.rect[2] - item.rect[0]) * (item.rect[3] - item.rect[1]))
        source = f"wechat title={window.title!r}"
        rect = window.rect
        output = out_dir / "wechat_window.png"
    try:
        path = capture_rect(rect, output)
        print(f"status=ok source={source} rect={rect}")
        print(f"screenshot={path}")
    except Exception as exc:
        path = _write_unavailable_placeholder(out_dir / "screenshot_unavailable.png", str(exc))
        print(f"status=unavailable source={source} rect={rect}")
        print(f"reason={exc}")
        print(f"diagnostic={path}")
    return 0


def _write_unavailable_placeholder(path: Path, reason: str) -> Path:
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 360), "#f6f7f9")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 620, 340), outline="#cbd2d9", width=2)
    draw.text((40, 48), "WhoChat screenshot probe", fill="#102a43")
    draw.text((40, 86), "Desktop capture is unavailable in this execution context.", fill="#52606d")
    draw.text((40, 124), reason[:110], fill="#9f1239")
    image.save(path)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
