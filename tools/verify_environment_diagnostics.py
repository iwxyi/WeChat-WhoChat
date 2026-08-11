from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "environment_diagnostics_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from whochat.app import create_app
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    checks = services.environment.checks()
    keys = {item.key: item for item in checks}
    for expected in [
        "python",
        "PySide6",
        "Pillow",
        "psutil",
        "ocr_provider",
        "paddle_worker_mode",
        "paddle_timeout",
        "paddle_cache",
        "data_dir",
        "config_dir",
        "database_path",
        "secret_backend",
    ]:
        if expected not in keys:
            raise RuntimeError(f"environment check missing {expected}: {keys}")
    if keys["python"].status not in {"ok", "warning"}:
        raise RuntimeError(f"python check failed unexpectedly: {keys['python']}")
    if keys["data_dir"].status != "ok" or keys["config_dir"].status != "ok":
        raise RuntimeError(f"path checks failed: data={keys['data_dir']} config={keys['config_dir']}")

    window = MainWindow(services)
    window._select_page("diagnostics")
    if window._environment_text is None or "python=" not in window._environment_text.toPlainText():
        raise RuntimeError("diagnostics page did not render environment checks")
    if window._window_match_text is None or "enabled_targets=" not in window._window_match_text.toPlainText():
        raise RuntimeError("diagnostics page did not render window matching checks")
    window._copy_diagnostics_bundle()
    clipboard = QApplication.clipboard().text()
    if "# environment" not in clipboard or "secret_backend=" not in clipboard or "ocr_provider=" not in clipboard or "# window_matching" not in clipboard:
        raise RuntimeError("diagnostics clipboard missing environment section")
    window._save_debug_sample()
    sample = sorted((DATA_DIR / "debug_samples").glob("sample-*"))[-1] / "diagnostics.json"
    text = sample.read_text(encoding="utf-8")
    if '"environment"' not in text or '"secret_backend"' not in text or '"ocr_provider"' not in text or '"window_matching"' not in text:
        raise RuntimeError("debug sample missing environment/window checks")
    print(f"checks={len(checks)} sample={sample}")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
