from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from datetime import datetime, timezone

from whochat.config import PrivacyConfig
from whochat.core.paths import app_data_dir
from whochat.storage.repositories import LogRepository, ReplyFeedbackRepository


@dataclass(frozen=True)
class RetentionTarget:
    key: str
    relative_dir: str
    days: int


@dataclass(frozen=True)
class RetentionResult:
    files_deleted: int
    dirs_deleted: int
    bytes_deleted: int
    skipped_files: int
    targets: tuple[str, ...]
    records_deleted: int = 0


class RetentionCleanupService:
    def __init__(
        self,
        logs: LogRepository | None = None,
        root: Path | None = None,
        reply_feedback: ReplyFeedbackRepository | None = None,
    ) -> None:
        self.logs = logs
        self.root = root or app_data_dir()
        self.reply_feedback = reply_feedback

    def cleanup(self, privacy: PrivacyConfig) -> RetentionResult:
        file_result = _cleanup_targets(self.root, _targets_from_config(privacy))
        feedback_deleted = _cleanup_reply_feedback(self.reply_feedback, privacy.reply_feedback_retention_days)
        targets = list(file_result.targets)
        if self.reply_feedback is not None and privacy.reply_feedback_retention_days > 0:
            targets.append("reply_feedback")
        result = RetentionResult(
            files_deleted=file_result.files_deleted,
            dirs_deleted=file_result.dirs_deleted,
            bytes_deleted=file_result.bytes_deleted,
            skipped_files=file_result.skipped_files,
            targets=tuple(targets),
            records_deleted=feedback_deleted,
        )
        if self.logs is not None:
            self.logs.append(
                "info",
                "retention",
                "cleanup_completed",
                "Expired local diagnostic files cleaned",
                {
                    "files_deleted": result.files_deleted,
                    "dirs_deleted": result.dirs_deleted,
                    "bytes_deleted": result.bytes_deleted,
                    "skipped_files": result.skipped_files,
                    "records_deleted": result.records_deleted,
                    "targets": list(result.targets),
                },
            )
        return result


def _targets_from_config(privacy: PrivacyConfig) -> tuple[RetentionTarget, ...]:
    return (
        RetentionTarget("logs", "logs", privacy.diagnostic_log_retention_days),
        RetentionTarget("debug_samples", "debug_samples", privacy.debug_sample_retention_days),
        RetentionTarget("capture", "capture", privacy.capture_retention_days),
        RetentionTarget("calibration", "calibration", privacy.calibration_retention_days),
    )


def _cleanup_targets(root: Path, targets: tuple[RetentionTarget, ...]) -> RetentionResult:
    root = root.resolve()
    now = time.time()
    files_deleted = 0
    dirs_deleted = 0
    bytes_deleted = 0
    skipped_files = 0
    cleaned_targets: list[str] = []

    for target in targets:
        if target.days <= 0:
            continue
        directory = (root / target.relative_dir).resolve()
        if not _is_inside(directory, root) or not directory.exists() or not directory.is_dir():
            continue
        cutoff = now - (target.days * 24 * 60 * 60)
        cleaned_targets.append(target.key)
        for path in sorted(directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if not _is_inside(path.resolve(), root):
                skipped_files += 1
                continue
            if path.is_file():
                if path.stat().st_mtime >= cutoff:
                    continue
                size = path.stat().st_size
                path.unlink()
                files_deleted += 1
                bytes_deleted += size
            elif path.is_dir() and path != directory:
                try:
                    path.rmdir()
                except OSError:
                    continue
                dirs_deleted += 1

    return RetentionResult(
        files_deleted=files_deleted,
        dirs_deleted=dirs_deleted,
        bytes_deleted=bytes_deleted,
        skipped_files=skipped_files,
        targets=tuple(cleaned_targets),
    )


def _cleanup_reply_feedback(repository: ReplyFeedbackRepository | None, retention_days: int) -> int:
    if repository is None or retention_days <= 0:
        return 0
    cutoff_ts = time.time() - (retention_days * 24 * 60 * 60)
    cutoff_iso = datetime.fromtimestamp(cutoff_ts, timezone.utc).isoformat()
    return repository.delete_older_than(cutoff_iso)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
