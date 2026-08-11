from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "schema_migration_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
DATA_DIR.mkdir(parents=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.storage.database import Database
from whochat.storage.migrations import MIGRATIONS
from whochat.storage.repositories import ContactRepository, ReplyFeedbackRepository, StrategyRepository


def main() -> int:
    db_path = DATA_DIR / "whochat.db"
    _build_v10_database(db_path)

    db = Database(db_path)
    db.migrate()
    db.migrate()

    with db.connect() as conn:
        versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        strategy_count = conn.execute("SELECT COUNT(*) AS count FROM strategies").fetchone()["count"]
    if versions != list(range(1, max(version for version, _sql in MIGRATIONS) + 1)):
        raise RuntimeError(f"unexpected migration versions: {versions}")
    if "reply_feedback" not in tables:
        raise RuntimeError(f"reply_feedback table missing after migration: {tables}")
    if strategy_count != 1:
        raise RuntimeError("existing v10 data was not preserved")

    StrategyRepository(db).ensure_defaults()
    contact = ContactRepository(db).create_or_get_by_display_name("迁移验证联系人")
    record = ReplyFeedbackRepository(db).append(
        contact_id=contact.id,
        strategy_id=contact.strategy_id,
        provider="Local Preview",
        status="local_preview",
        suggestion_label="稳妥版",
        suggestion_text="迁移后可写入反馈",
        risk="low",
        feedback="useful",
        context_hash="e" * 64,
        page_type="chat_dm",
        message_count=1,
        memory_count=0,
    )
    if not record.id.startswith("reply_feedback_"):
        raise RuntimeError(f"reply feedback repository failed after migration: {record}")

    print(f"migrated_versions={len(versions)} reply_feedback={record.id}")
    return 0


def _build_v10_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        for version, sql in MIGRATIONS:
            if version > 10:
                continue
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        conn.execute(
            """
            INSERT INTO strategies
            (id, name, goal, mode, tone, avoid, reply_variants, requires_manual_reply, created_at, updated_at, archived)
            VALUES
            ('default', '默认', '迁移前默认目标', '默认', '自然、清晰', '', '稳妥版,简短版,推进版', 0,
             '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0)
            """
        )


if __name__ == "__main__":
    raise SystemExit(main())
