from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.platform.window_tracker import find_wechat_windows


def main() -> int:
    windows = find_wechat_windows()
    if not windows:
        print("wechat_windows=0")
        return 0
    print(f"wechat_windows={len(windows)}")
    for window in windows:
        print(
            f"hwnd={window.hwnd} process={window.process_name!r} "
            f"title={window.title!r} rect={window.rect} visible={window.visible} "
            f"foreground={window.foreground} covered={window.covered} diagnostic={window.diagnostic!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
