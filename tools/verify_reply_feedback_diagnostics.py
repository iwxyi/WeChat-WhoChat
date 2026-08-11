from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "reply_feedback_diagnostics_verify"
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
    contact = services.contacts.create_or_get_by_display_name("反馈诊断联系人")
    services.reply_feedback.append(
        contact_id=contact.id,
        strategy_id=contact.strategy_id,
        provider="Local Preview",
        status="local_preview",
        suggestion_label="稳妥版",
        suggestion_text="建议文本 13812345678 sk-feedback-secret-token-value",
        risk="low",
        feedback="useful",
        context_hash="a" * 64,
        page_type="chat_dm",
        message_count=2,
        memory_count=1,
    )
    services.reply_feedback.append(
        contact_id=contact.id,
        strategy_id=contact.strategy_id,
        provider="Local Preview",
        status="local_preview",
        suggestion_label="简短版",
        suggestion_text="另一条建议",
        risk="medium",
        feedback="bad",
        context_hash="b" * 64,
        page_type="chat_dm",
        message_count=2,
        memory_count=1,
    )

    window = MainWindow(services)
    window._select_page("diagnostics")
    window._refresh_generation_log_text()
    diagnostics_text = window._generation_log_text.toPlainText()
    if "回复反馈：count=2 useful=1 bad=1" not in diagnostics_text:
        raise RuntimeError(f"diagnostics page missing feedback summary: {diagnostics_text}")

    window._copy_diagnostics_bundle()
    clipboard = QApplication.clipboard().text()
    if "# reply_feedback" not in clipboard or "useful=1" not in clipboard or "bad=1" not in clipboard:
        raise RuntimeError(f"diagnostics bundle missing feedback section: {clipboard}")
    if "13812345678" in clipboard or "sk-feedback-secret-token-value" in clipboard:
        raise RuntimeError(f"diagnostics bundle leaked feedback sensitive preview: {clipboard}")

    window._save_debug_sample()
    sample = sorted((DATA_DIR / "debug_samples").glob("sample-*"))[-1] / "diagnostics.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    if len(payload.get("reply_feedback", [])) != 2:
        raise RuntimeError(f"debug sample missing reply feedback rows: {payload.keys()}")
    serialized = json.dumps(payload, ensure_ascii=False)
    if "13812345678" in serialized or "sk-feedback-secret-token-value" in serialized:
        raise RuntimeError("debug sample leaked feedback sensitive preview")

    print("reply_feedback_diagnostics=ok")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
