from __future__ import annotations

import faulthandler
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from whochat.core.paths import app_data_dir


_CRASH_LOG_HANDLE = None


def configure_process_diagnostics() -> Path:
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    crash_log = log_dir / "crash.log"
    global _CRASH_LOG_HANDLE
    if _CRASH_LOG_HANDLE is None:
        _CRASH_LOG_HANDLE = crash_log.open("a", encoding="utf-8")
    faulthandler.enable(file=_CRASH_LOG_HANDLE, all_threads=True)
    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook
    _append_line(crash_log, "diagnostics_started")
    return crash_log


def diagnostics_log_path(name: str) -> Path:
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in {"_", "-", "."}).strip(".")
    if not safe_name:
        safe_name = "diagnostics.log"
    if not safe_name.endswith(".log"):
        safe_name += ".log"
    return app_data_dir() / "logs" / safe_name


def append_diagnostics_log(name: str, message: str) -> Path:
    path = diagnostics_log_path(name)
    ts = datetime.now(timezone.utc).isoformat()
    _append_line(path, f"{ts} {message}")
    return path


def configure_native_runtime_limits() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("FLAGS_allocator_strategy", "auto_growth")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def _excepthook(exc_type, exc_value, exc_traceback) -> None:
    crash_log = app_data_dir() / "logs" / "crash.log"
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    _append_line(crash_log, "unhandled_exception\n" + text)
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    crash_log = app_data_dir() / "logs" / "crash.log"
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    _append_line(crash_log, f"thread_exception:{args.thread.name if args.thread else '-'}\n{text}")
    threading.__excepthook__(args)


def _append_line(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")
