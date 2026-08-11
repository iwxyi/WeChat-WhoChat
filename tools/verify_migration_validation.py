from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.storage.database import validate_migrations
from whochat.storage.migrations import MIGRATIONS


def main() -> int:
    validate_migrations(MIGRATIONS)
    _expect_error([], "empty")
    _expect_error([(1, ""), (1, "")], "duplicate")
    _expect_error([(1, ""), (3, "")], "missing")
    _expect_error([(2, ""), (1, "")], "ordered")
    _expect_error([(0, "")], "positive")
    _expect_error([("1", "")], "positive")
    print(f"migration_validation=ok count={len(MIGRATIONS)}")
    return 0


def _expect_error(migrations, marker: str) -> None:
    try:
        validate_migrations(migrations)
    except ValueError as exc:
        if marker not in str(exc):
            raise RuntimeError(f"expected error marker {marker!r}, got {exc}") from exc
        return
    raise RuntimeError(f"expected migration validation error for {migrations!r}")


if __name__ == "__main__":
    raise SystemExit(main())
