from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "floating_preferences_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QPushButton

from whochat.app import create_app
from whochat.services.bootstrap import build_services
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    floating = FloatingWidget()
    _assert_edge(floating, "top", (200, 200, 500, 500), "顶部")
    _assert_edge(floating, "bottom", (200, 200, 500, 500), "底部")
    _assert_edge(floating, "right", (100, 100, 300, 300), "右侧")
    _assert_edge(floating, "left", (500, 100, 700, 300), "左侧")

    floating.apply_preferences(placement_preference="right", opacity_percent=82, suggestion_count=2)
    if floating.placement_preference != "right" or floating.suggestion_count != 2:
        raise RuntimeError("floating preferences were not stored on widget")
    if abs(floating.windowOpacity() - 0.82) > 0.01:
        raise RuntimeError(f"floating opacity mismatch: {floating.windowOpacity()}")
    buttons = [button for button in floating.findChildren(QPushButton) if button.objectName() == "FloatingSuggestionButton"]
    visible_buttons = [button for button in buttons if not button.isHidden()]
    if len(visible_buttons) != 2:
        raise RuntimeError(f"expected 2 suggestion buttons, got {len(visible_buttons)}")

    services = build_services()
    window = MainWindow(services)
    window.attach_floating_widget(floating)
    floating.hide_for_window_state("无目标")
    window._toggle_floating()
    if floating.isVisible():
        raise RuntimeError("main window should not show floating widget when no visible target exists")
    window._select_page("settings")
    window._floating_placement.setCurrentText("left")
    window._floating_opacity.setValue(88)
    window._floating_suggestion_count.setValue(1)
    window._save_ai_settings()
    config_text = (DATA_DIR / "config" / "config.json").read_text(encoding="utf-8")
    if '"placement_preference": "left"' not in config_text or '"opacity_percent": 88' not in config_text:
        raise RuntimeError(f"floating config was not persisted: {config_text}")
    if floating.placement_preference != "left" or floating.suggestion_count != 1:
        raise RuntimeError("saved floating settings were not applied to widget")

    print(f"placement={floating.placement_preference} opacity={floating.windowOpacity():.2f} buttons={floating.suggestion_count}")
    window.close()
    floating.close()
    app.quit()
    return 0


def _assert_edge(floating: FloatingWidget, preference: str, rect: tuple[int, int, int, int], expected_edge: str) -> None:
    floating.apply_preferences(placement_preference=preference, opacity_percent=96, suggestion_count=3)
    placement = floating._choose_placement(rect)
    if placement is None or placement.edge != expected_edge:
        raise RuntimeError(f"{preference} placement mismatch: {placement}")


if __name__ == "__main__":
    raise SystemExit(main())
