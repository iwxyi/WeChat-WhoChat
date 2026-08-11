from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.core.runtime import Rect, TargetApp, WindowSnapshot, WindowState
from whochat.platform.adapters import WeChatAdapter


def main() -> int:
    cases = [
        ("compact", Rect(0, 0, 640, 520)),
        ("standard", Rect(120, 80, 1220, 820)),
        ("wide", Rect(-1800, 40, 180, 1040)),
        ("tall_secondary", Rect(1920, 0, 2920, 1400)),
    ]
    adapter = WeChatAdapter()
    for name, rect in cases:
        snapshot = WindowSnapshot(
            target=TargetApp.WECHAT,
            hwnd=100,
            title="微信",
            process_name="WeChat.exe",
            rect=rect,
            state=WindowState.VISIBLE,
        )
        layout = adapter.estimate_layout(snapshot)
        if layout is None:
            raise RuntimeError(f"{name}: layout missing")
        if layout.window_rect != rect:
            raise RuntimeError(f"{name}: window rect changed")
        if not (layout.nav_rect.left == rect.left and layout.input_rect.right == rect.right):
            raise RuntimeError(f"{name}: layout does not respect window edges")
        if layout.message_rect.width < 280 or layout.message_rect.height < 160:
            raise RuntimeError(f"{name}: message region too small: {layout.message_rect}")
        if not (layout.nav_rect.right <= layout.chat_list_rect.left <= layout.chat_list_rect.right <= layout.content_rect.left):
            raise RuntimeError(f"{name}: horizontal regions overlap")
        if not (layout.title_rect.bottom <= layout.message_rect.top <= layout.message_rect.bottom <= layout.input_rect.top):
            raise RuntimeError(f"{name}: vertical regions overlap")
        if layout.source.value != "auto":
            raise RuntimeError(f"{name}: expected auto layout source")
        print(f"{name}: content={layout.content_rect.as_tuple()} message={layout.message_rect.as_tuple()} reason={layout.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
