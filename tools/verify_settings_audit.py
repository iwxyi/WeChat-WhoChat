from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "settings_audit_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    window = MainWindow(services)
    window._ai_provider.setCurrentText("OpenAI Compatible")
    window._ai_base_url.setText("https://audit.example.test/v1")
    window._ai_model.setText("audit-model")
    window._ai_api_key.setText("sk-settings-audit-secret-value")
    window._privacy_debug_screenshots.setChecked(True)
    window._capture_auto_enabled.setChecked(False)
    window._capture_debounce.setValue(1200)
    window._floating_placement.setCurrentText("top")
    window._floating_opacity.setValue(87)
    window._floating_suggestion_count.setValue(2)
    window._save_ai_settings()

    rows = services.settings_audit.tail(5)
    if not rows:
        raise RuntimeError("settings audit was not written")
    latest = rows[0]
    changes = latest.changes_json
    for expected in [
        "ai.base_url",
        "ai.model",
        "ai.api_key",
        "privacy.save_debug_screenshots",
        "capture.auto_capture_enabled",
        "floating.placement_preference",
        "floating.opacity_percent",
        "floating.suggestion_count",
    ]:
        if expected not in changes:
            raise RuntimeError(f"settings audit missing {expected}: {changes}")
    if "sk-settings-audit-secret-value" in changes or "api_key\"" not in changes:
        raise RuntimeError(f"settings audit leaked or missed API key change marker: {changes}")
    if latest.actor != "local_user" or latest.scope != "settings":
        raise RuntimeError(f"settings audit metadata mismatch: {latest}")
    print(f"audits={len(rows)} changes_chars={len(changes)} backend={latest.secret_backend}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
