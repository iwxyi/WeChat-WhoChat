from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.config import default_target_windows
from whochat.platform.window_tracker import diagnose_target_windows, foreground_window_handle


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    targets = [target for target in default_target_windows() if target.enabled]
    candidates = diagnose_target_windows(targets)
    if not candidates:
        print("status=no_related_windows")
        print(f"foreground_hwnd={foreground_window_handle() or '-'}")
        return 0

    print(f"status=ok count={len(candidates)}")
    print(f"foreground_hwnd={foreground_window_handle() or '-'}")
    for item in candidates[:20]:
        print(
            f"hwnd={item.hwnd} process={item.process_name or '-'} "
            f"target={item.target_app or '-'} label={item.app_label or '-'} "
            f"foreground={item.foreground} matched={item.matched} reason={item.reason} title={item.title}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
