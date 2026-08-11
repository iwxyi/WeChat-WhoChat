from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "provider_health_ui_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    services.reply_generator.consecutive_cloud_failures = 3
    services.reply_generator.provider_health_status = "backoff"
    services.reply_generator.provider_backoff_until = datetime.now(timezone.utc) + timedelta(minutes=10)

    window = MainWindow(services)
    window._select_page("settings")
    if window._ai_health_label is None or "backoff" not in window._ai_health_label.text():
        raise RuntimeError("settings page did not show provider backoff state")
    window._reset_ai_provider_health()
    summary = services.reply_generator.provider_health_summary()
    if "status=healthy" not in summary or "failures=0" not in summary:
        raise RuntimeError(f"provider health was not reset: {summary}")
    if "healthy" not in window._ai_health_label.text():
        raise RuntimeError(f"provider health label was not updated: {window._ai_health_label.text()}")
    logs = services.logs.tail(5)
    if not any(item.event == "provider_health_reset" for item in logs):
        raise RuntimeError("provider health reset was not logged")
    services.reply_generator.consecutive_cloud_failures = 2
    services.reply_generator.provider_health_status = "backoff"
    services.reply_generator.provider_backoff_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    services.reply_generator._persist_provider_health()
    window._refresh_provider_health()
    refreshed = services.reply_generator.provider_health_summary()
    if "status=recovering" not in refreshed or "recovering" not in window._ai_health_label.text():
        raise RuntimeError(f"expired backoff did not refresh in UI: {refreshed} / {window._ai_health_label.text()}")
    print(summary)
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
