from __future__ import annotations

from pathlib import Path


def capture_rect(rect: tuple[int, int, int, int], output: Path) -> Path:
    import mss

    left, top, right, bottom = rect
    monitor = {
        "left": left,
        "top": top,
        "width": max(1, right - left),
        "height": max(1, bottom - top),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        image = sct.grab(monitor)
        mss.tools.to_png(image.rgb, image.size, output=str(output))
    return output

