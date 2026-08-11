from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "diagnostics_actions_verify"
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
    window = MainWindow(services)
    window._select_page("diagnostics")
    window.append_log("verify info log", "info")
    window.append_log("verify warning log", "warning")
    window.append_log("verify error log", "error")
    sensitive_values = [
        "sk-diagnostic-secret-token-value",
        "Authorization: Bearer diagnosticBearerSecret12345",
        "Bearer standaloneBearerSecret12345",
        "api_key=diagnosticApiKeySecret12345",
        "debug.user@example.com",
        "https://example.com/private/path?token=secret",
        "13812345678",
        "123456789012345",
    ]
    window.append_log(" ".join(sensitive_values), "error")
    window._log_level_filter.setCurrentText("warning")
    filtered = window._log_text.toPlainText()
    if "verify warning log" not in filtered or "verify info log" in filtered or "verify error log" in filtered:
        raise RuntimeError(f"diagnostics log filter did not isolate warnings: {filtered}")
    window._copy_diagnostics_bundle()
    clipboard = QApplication.clipboard().text()
    if "# runtime" not in clipboard or "# files" not in clipboard or "# capture_samples" not in clipboard:
        raise RuntimeError("diagnostics clipboard bundle missing expected sections")
    if "capture_perf=暂无" not in clipboard:
        raise RuntimeError("diagnostics clipboard should include empty capture performance state")
    if "verify info log" not in clipboard or "verify error log" not in clipboard:
        raise RuntimeError("diagnostics clipboard should include unfiltered logs")
    _assert_redacted("clipboard", clipboard, sensitive_values)

    window._save_debug_sample()
    samples = sorted((DATA_DIR / "debug_samples").glob("sample-*"))
    if not samples:
        raise RuntimeError("debug sample directory was not created")
    sample_file = samples[-1] / "diagnostics.json"
    if not sample_file.exists():
        raise RuntimeError("diagnostics.json was not exported")
    text = sample_file.read_text(encoding="utf-8")
    if '"scope": "diagnostics"' not in text or '"runtime"' not in text:
        raise RuntimeError("diagnostics sample missing expected payload")
    _assert_redacted("diagnostics.json", text, sensitive_values)
    print(f"clipboard_chars={len(clipboard)} sample={sample_file}")
    window.close()
    app.quit()
    return 0


def _assert_redacted(name: str, text: str, raw_values: list[str]) -> None:
    for value in raw_values:
        if value in text:
            raise RuntimeError(f"{name} leaked raw sensitive value: {value}")
    for marker in [
        "[已脱敏:密钥]",
        "[已脱敏:认证头]",
        "[已脱敏:Bearer]",
        "[已脱敏:API Key]",
        "[已脱敏:邮箱]",
        "[已脱敏:链接]",
        "[已脱敏:手机号]",
        "[已脱敏:长数字]",
    ]:
        if marker not in text:
            raise RuntimeError(f"{name} missing redaction marker: {marker}")


if __name__ == "__main__":
    raise SystemExit(main())
