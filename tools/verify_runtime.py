from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["WHOCHAT_DATA_DIR"] = str(ROOT / "tmp" / "runtime_verify")
os.environ["WHOCHAT_DB_PATH"] = str(ROOT / "tmp" / "runtime_verify" / "whochat.db")

from whochat.capture.policy import CaptureGate
from whochat.core.runtime import CapturePolicy, PageType, RegionSource, TargetApp, ThemeMode, WindowState
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services


def main() -> int:
    services = build_services()
    window = WindowInfo(
        hwnd=100,
        title="微信",
        process_name="Weixin",
        rect=(0, 0, 1200, 800),
        visible=True,
    )
    state = services.runtime.update_from_window_info(window)
    if state.window.state != WindowState.VISIBLE:
        raise RuntimeError("runtime did not mark test window visible")
    if state.layout is None:
        raise RuntimeError("layout was not estimated")
    if state.layout.chat_list_rect.left <= state.layout.nav_rect.left:
        raise RuntimeError("layout regions are not ordered")
    if state.page.page_type != PageType.UNKNOWN or state.page.can_generate_reply:
        raise RuntimeError("page classifier should block replies before OCR evidence")
    calibration = services.calibrations.create_from_layout(
        name="runtime verify calibration",
        target=TargetApp.WECHAT,
        window_rect=state.window.rect,
        layout=state.layout,
        theme=ThemeMode.UNKNOWN,
        active=True,
    )
    calibrated = services.runtime.refresh_current()
    if calibrated.layout is None or calibrated.layout.source != RegionSource.CALIBRATED:
        raise RuntimeError("active calibration was not applied")
    if services.calibrations.get_active(TargetApp.WECHAT).id != calibration.id:
        raise RuntimeError("active calibration lookup failed")
    paused = services.runtime.set_paused(True)
    if not paused.paused or paused.capture_decision.should_capture:
        raise RuntimeError("pause state did not block capture")

    gate = CaptureGate(CapturePolicy(screenshot_min_interval_ms=0, min_hash_distance=4))
    out = ROOT / "tmp" / "runtime_verify"
    out.mkdir(parents=True, exist_ok=True)
    first = out / "first.png"
    second = out / "second.png"
    Image.new("RGB", (64, 64), (240, 240, 240)).save(first)
    Image.new("RGB", (64, 64), (240, 240, 240)).save(second)

    services.runtime.set_paused(False)
    state = services.runtime.update_from_window_info(window)
    first_decision = gate.evaluate(state, first)
    second_decision = gate.evaluate(state, second)
    if not first_decision.should_capture:
        raise RuntimeError("first screenshot should be allowed")
    if second_decision.should_capture:
        raise RuntimeError("duplicate screenshot should be skipped")

    print(f"status={state.status_label}")
    print(f"layout_confidence={state.layout.confidence:.2f}")
    print(f"capture_reason={second_decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
