from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "target_windows_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.config import ConfigStore, TargetWindowConfig
from whochat.core.runtime import TargetApp
from whochat.platform.adapters import WeChatAdapter
import whochat.platform.window_follow as window_follow
from whochat.platform.window_follow import TargetWindowFollowController
from whochat.platform.window_tracker import _match_target
import whochat.platform.window_tracker as window_tracker
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()

    store = ConfigStore()
    config = store.load()
    if [target.app_id for target in config.targets][:2] != ["wechat", "telegram"]:
        raise RuntimeError(f"default targets missing expected presets: {config.targets}")
    telegram = next(target for target in config.targets if target.app_id == "telegram")
    wechat_default = next(target for target in config.targets if target.app_id == "wechat")
    if "图片和视频" not in wechat_default.exclude_title_keywords:
        raise RuntimeError(f"wechat default exclusions missing media window: {wechat_default.exclude_title_keywords}")
    telegram.enabled = True
    store.save(config)
    loaded = store.load()
    if not next(target for target in loaded.targets if target.app_id == "telegram").enabled:
        raise RuntimeError("target window config was not persisted")
    services = build_services()
    window = MainWindow(services)
    window._target_checkboxes["generic_chat"].setChecked(True)
    window._target_process_inputs["generic_chat"].setText("Slack.exe; Discord.exe, Slack.exe")
    window._target_title_inputs["generic_chat"].setText("Slack\nDiscord")
    window._target_exclude_title_inputs["generic_chat"].setText("Preferences; Settings")
    window._config.targets.append(
        TargetWindowConfig(
            app_id="custom_signal",
            label="Signal",
            enabled=True,
            process_names=["Signal.exe"],
            title_keywords=["Signal"],
            exclude_title_keywords=["Settings"],
        )
    )
    window._refresh_target_grid()
    if "custom_signal" not in window._target_checkboxes:
        raise RuntimeError("custom target did not render")
    window._remove_target_app("custom_signal")
    if "custom_signal" in window._target_checkboxes:
        raise RuntimeError("custom target was not removed from UI")
    window._save_ai_settings()
    reloaded = store.load()
    generic = next(target for target in reloaded.targets if target.app_id == "generic_chat")
    if not generic.enabled:
        raise RuntimeError("generic target was not enabled from UI")
    if generic.process_names != ["Slack.exe", "Discord.exe"] or generic.title_keywords != ["Slack", "Discord"]:
        raise RuntimeError(f"target rules were not normalized from UI: {generic}")
    if generic.exclude_title_keywords != ["Preferences", "Settings"]:
        raise RuntimeError(f"target exclusion rules were not normalized from UI: {generic}")
    if any(target.app_id == "custom_signal" for target in reloaded.targets):
        raise RuntimeError("removed custom target was persisted")
    wechat_target = next(target for target in reloaded.targets if target.app_id == "wechat")
    false_positive = _match_target([wechat_target], "app.py - WeChat-WhoChat - Visual Studio Code", "")
    if false_positive is not None:
        raise RuntimeError(f"project title should not match WeChat target: {false_positive}")
    exact_title = _match_target([wechat_target], "WeChat", "")
    if exact_title is None:
        raise RuntimeError("exact WeChat window title should still match when process is unavailable")
    media_window = _match_target([wechat_target], "图片和视频", "Weixin.exe")
    if media_window is not None:
        raise RuntimeError(f"wechat media preview should be excluded from chat capture: {media_window}")

    adapter = WeChatAdapter()
    generic_window = WindowInfo(
        hwnd=22,
        title="Telegram",
        process_name="Telegram.exe",
        rect=(0, 0, 1200, 800),
        visible=True,
        target_app="telegram",
        app_label="Telegram",
    )
    snapshot = adapter.window_snapshot(generic_window)
    layout = adapter.estimate_layout(snapshot)
    if snapshot.target != TargetApp.GENERIC_CHAT:
        raise RuntimeError(f"telegram target should map to generic_chat, got {snapshot.target}")
    if layout is None or layout.nav_rect.width != 0 or layout.confidence >= 0.5:
        raise RuntimeError(f"generic layout should be conservative and nav-free, got {layout}")

    windows = [
        WindowInfo(1, "微信", "WeChat.exe", (0, 0, 800, 600), True, "wechat", "微信"),
        WindowInfo(2, "Telegram", "Telegram.exe", (0, 0, 600, 500), True, "telegram", "Telegram"),
    ]
    original_find = window_follow.find_target_windows
    original_foreground = window_follow.foreground_window_handle
    try:
        window_follow.find_target_windows = lambda _targets: windows
        window_follow.foreground_window_handle = lambda: 2
        controller = TargetWindowFollowController(reloaded.targets)
        focused = controller.poll_once()
        if focused is None or focused.hwnd != 2:
            raise RuntimeError(f"focused supported window should win, got {focused}")
        window_follow.foreground_window_handle = lambda: 999
        fallback = controller.poll_once()
        if fallback is None or fallback.hwnd != 1:
            raise RuntimeError(f"largest supported window should be fallback, got {fallback}")
    finally:
        window_follow.find_target_windows = original_find
        window_follow.foreground_window_handle = original_foreground

    original_process_ids = window_tracker._process_ids_by_names
    original_process_name_by_pid = window_tracker._process_name_by_pid
    original_enum = getattr(window_tracker, "find_target_windows")
    try:
        window_tracker._process_ids_by_names = lambda _names: {}
        window_tracker._process_name_by_pid = lambda pid: "WeChat.exe" if pid == 4242 else ""
        fallback_target = _match_target([wechat_target], "Not a matching title", window_tracker._process_name_by_pid(4242))
        if fallback_target is None or fallback_target.app_id != "wechat":
            raise RuntimeError("process-name fallback should allow matching even when title does not match")
    finally:
        window_tracker._process_ids_by_names = original_process_ids
        window_tracker._process_name_by_pid = original_process_name_by_pid

    print(f"targets={len(reloaded.targets)} focused={focused.app_label} fallback={fallback.app_label} generic={generic.process_names}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
