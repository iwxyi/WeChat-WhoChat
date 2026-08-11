from __future__ import annotations

import sqlite3
from pathlib import Path

from whochat.core.paths import database_path
from whochat.storage.migrations import MIGRATIONS


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def migrate(self) -> None:
        validate_migrations(MIGRATIONS)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))


def validate_migrations(migrations: list[tuple[int, str]]) -> None:
    versions = [version for version, _sql in migrations]
    if not versions:
        raise ValueError("database migrations are empty")
    invalid = [version for version in versions if not isinstance(version, int) or version <= 0]
    if invalid:
        raise ValueError(f"database migration versions must be positive integers: {invalid}")
    duplicates = sorted({version for version in versions if versions.count(version) > 1})
    if duplicates:
        raise ValueError(f"duplicate database migration versions: {duplicates}")
    expected = list(range(1, max(versions) + 1))
    if versions != expected:
        missing = [version for version in expected if version not in versions]
        raise ValueError(f"database migrations must be ordered and contiguous; missing={missing} actual={versions}")
