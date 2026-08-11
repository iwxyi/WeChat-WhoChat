from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.capture.policy import CaptureGate
from whochat.core.models import utc_now_iso
from whochat.core.runtime import CapturePolicy, LayoutCalibration, RelativeRect, TargetApp, ThemeMode
from whochat.platform.adapters import WeChatAdapter
from whochat.platform.window_tracker import WindowInfo


class FakeCalibrations:
    def __init__(self, calibration: LayoutCalibration) -> None:
        self.calibration = calibration

    def get_active(self, _target: TargetApp) -> LayoutCalibration:
        return self.calibration


def _window(hwnd: int, rect: tuple[int, int, int, int]) -> WindowInfo:
    return WindowInfo(hwnd=hwnd, title="微信", process_name="Weixin", rect=rect, visible=True)


def _shifted(left_rect: tuple[int, int, int, int], right_rect: tuple[int, int, int, int]) -> tuple[int, int]:
    return (right_rect[0] - left_rect[0], right_rect[1] - left_rect[1])


def main() -> int:
    now = utc_now_iso()
    calibration = LayoutCalibration(
        id="cal_move_verify",
        target=TargetApp.WECHAT,
        name="move verify",
        theme=ThemeMode.UNKNOWN,
        dpi_scale=1.0,
        nav_rect=RelativeRect(0.0, 0.0, 0.08, 1.0),
        chat_list_rect=RelativeRect(0.08, 0.0, 0.34, 1.0),
        content_rect=RelativeRect(0.34, 0.0, 1.0, 1.0),
        title_rect=RelativeRect(0.34, 0.0, 1.0, 0.08),
        message_rect=RelativeRect(0.34, 0.08, 1.0, 0.78),
        input_rect=RelativeRect(0.34, 0.78, 1.0, 1.0),
        active=True,
        created_at=now,
        updated_at=now,
    )
    adapter = WeChatAdapter(calibrations=FakeCalibrations(calibration))
    first_snapshot = adapter.window_snapshot(_window(8801, (100, 120, 1300, 920)))
    moved_snapshot = adapter.window_snapshot(_window(8801, (420, 260, 1620, 1060)))
    first_layout = adapter.estimate_layout(first_snapshot)
    moved_layout = adapter.estimate_layout(moved_snapshot)
    if first_layout is None or moved_layout is None:
        raise RuntimeError("expected calibrated layouts")
    if _shifted(first_layout.message_rect.as_tuple(), moved_layout.message_rect.as_tuple()) != (320, 140):
        raise RuntimeError(
            f"pure window move should translate message rect only: {first_layout.message_rect.as_tuple()} -> {moved_layout.message_rect.as_tuple()}"
        )
    if first_layout.message_rect.width != moved_layout.message_rect.width or first_layout.message_rect.height != moved_layout.message_rect.height:
        raise RuntimeError("pure window move should preserve calibrated message region size")

    gate = CaptureGate(CapturePolicy(window_stable_delay_ms=10_000, screenshot_min_interval_ms=0))
    first_state = type("State", (), {"paused": False, "window": first_snapshot, "layout": first_layout})()
    moved_state = type("State", (), {"paused": False, "window": moved_snapshot, "layout": moved_layout})()
    first_decision = gate.evaluate(first_state)
    moved_decision = gate.evaluate(moved_state)
    if not first_decision.should_capture or not moved_decision.should_capture:
        raise RuntimeError(f"pure move should remain capturable: first={first_decision} moved={moved_decision}")

    resized_snapshot = adapter.window_snapshot(_window(8801, (420, 260, 1720, 1060)))
    resized_layout = adapter.estimate_layout(resized_snapshot)
    resized_state = type("State", (), {"paused": False, "window": resized_snapshot, "layout": resized_layout})()
    resized_decision = gate.evaluate(resized_state)
    if resized_decision.should_capture or "区域刚变化" not in resized_decision.reason:
        raise RuntimeError(f"resize should still wait for layout stability: {resized_decision}")

    print(
        "move_ok "
        f"first={first_layout.message_rect.as_tuple()} "
        f"moved={moved_layout.message_rect.as_tuple()} "
        f"resize_decision={resized_decision.reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
