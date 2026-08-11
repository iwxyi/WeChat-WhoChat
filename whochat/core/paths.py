from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    override = os.environ.get("WHOCHAT_DATA_DIR")
    if override:
        return Path(override)
    return _repo_root() / ".whochat-data"


def config_dir() -> Path:
    override = os.environ.get("WHOCHAT_CONFIG_DIR")
    if override:
        return Path(override)
    return app_data_dir()


def database_path() -> Path:
    override = os.environ.get("WHOCHAT_DB_PATH")
    if override:
        return Path(override)
    return app_data_dir() / "whochat.db"
