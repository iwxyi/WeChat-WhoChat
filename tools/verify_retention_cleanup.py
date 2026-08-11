from __future__ import annotations

import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "retention_verify" / "data"
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.config import PrivacyConfig
from whochat.storage.database import Database
from whochat.storage.repositories import ContactRepository, ReplyFeedbackRepository, StrategyRepository
from whochat.services.retention import RetentionCleanupService


def main() -> int:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)

    old_files = [
        DATA_DIR / "logs" / "old.log",
        DATA_DIR / "debug_samples" / "sample-old" / "diagnostics.json",
        DATA_DIR / "capture" / "job_old.png",
        DATA_DIR / "calibration" / "old_window.png",
    ]
    new_files = [
        DATA_DIR / "logs" / "new.log",
        DATA_DIR / "debug_samples" / "sample-new" / "diagnostics.json",
        DATA_DIR / "capture" / "job_new.png",
        DATA_DIR / "calibration" / "current_window.png",
    ]
    protected_files = [
        DATA_DIR / "whochat.db",
        DATA_DIR / "config" / "config.json",
        DATA_DIR / "exports" / "whochat-all.json",
        DATA_DIR / "ocr_cache" / "home" / "model.bin",
    ]
    for path in old_files + new_files + protected_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    old_ts = time.time() - 10 * 24 * 60 * 60
    for path in old_files:
        os.utime(path, (old_ts, old_ts))

    service = RetentionCleanupService(root=DATA_DIR)
    result = service.cleanup(
        PrivacyConfig(
            diagnostic_log_retention_days=7,
            debug_sample_retention_days=7,
            capture_retention_days=7,
            calibration_retention_days=7,
        )
    )

    missing_old = [str(path) for path in old_files if path.exists()]
    missing_new = [str(path) for path in new_files if not path.exists()]
    missing_protected = [str(path) for path in protected_files if not path.exists()]
    if missing_old:
        raise RuntimeError(f"old files were not cleaned: {missing_old}")
    if missing_new:
        raise RuntimeError(f"new files were deleted: {missing_new}")
    if missing_protected:
        raise RuntimeError(f"protected files were deleted: {missing_protected}")
    if result.files_deleted != len(old_files):
        raise RuntimeError(f"expected {len(old_files)} deleted files, got {result.files_deleted}")
    if set(result.targets) != {"logs", "debug_samples", "capture", "calibration"}:
        raise RuntimeError(f"unexpected targets: {result.targets}")

    db = Database(DATA_DIR / "retention_feedback.db")
    db.migrate()
    StrategyRepository(db).ensure_defaults()
    contacts = ContactRepository(db)
    feedback = ReplyFeedbackRepository(db)
    contact = contacts.create_or_get_by_display_name("Retention Feedback")
    old_feedback = feedback.append(
        contact_id=contact.id,
        strategy_id=contact.strategy_id,
        provider="Local Preview",
        status="local_preview",
        suggestion_label="old",
        suggestion_text="old feedback",
        risk="low",
        feedback="useful",
        context_hash="c" * 64,
        page_type="chat_dm",
        message_count=1,
        memory_count=0,
    )
    new_feedback = feedback.append(
        contact_id=contact.id,
        strategy_id=contact.strategy_id,
        provider="Local Preview",
        status="local_preview",
        suggestion_label="new",
        suggestion_text="new feedback",
        risk="low",
        feedback="bad",
        context_hash="d" * 64,
        page_type="chat_dm",
        message_count=1,
        memory_count=0,
    )
    old_iso = datetime.fromtimestamp(old_ts, timezone.utc).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE reply_feedback SET ts = ? WHERE id = ?", (old_iso, old_feedback.id))
    result_with_db = RetentionCleanupService(root=DATA_DIR, reply_feedback=feedback).cleanup(
        PrivacyConfig(
            diagnostic_log_retention_days=7,
            debug_sample_retention_days=7,
            capture_retention_days=7,
            calibration_retention_days=7,
            reply_feedback_retention_days=7,
        )
    )
    remaining = feedback.tail(10)
    if result_with_db.records_deleted != 1:
        raise RuntimeError(f"expected one old feedback record deleted, got {result_with_db.records_deleted}")
    if [row.id for row in remaining] != [new_feedback.id]:
        raise RuntimeError(f"retention should keep only new feedback: {remaining}")
    if "reply_feedback" not in result_with_db.targets:
        raise RuntimeError(f"reply feedback target missing: {result_with_db.targets}")
    print(
        f"files_deleted={result.files_deleted} dirs_deleted={result.dirs_deleted} "
        f"bytes_deleted={result.bytes_deleted} records_deleted={result_with_db.records_deleted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
