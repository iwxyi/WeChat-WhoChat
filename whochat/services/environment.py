from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path
import platform
import sys

from whochat.config import ConfigStore
from whochat.core.paths import app_data_dir, config_dir, database_path


@dataclass(frozen=True)
class EnvironmentCheck:
    key: str
    status: str
    detail: str


class EnvironmentDiagnosticsService:
    def checks(self) -> list[EnvironmentCheck]:
        config = ConfigStore().load()
        return [
            EnvironmentCheck("python", "ok" if (3, 11) <= sys.version_info[:2] < (3, 14) else "warning", sys.version.split()[0]),
            EnvironmentCheck("platform", "ok", f"{platform.system()} {platform.release()} {platform.machine()}"),
            _package_check("PySide6", "PySide6"),
            _package_check("Pillow", "PIL"),
            _package_check("mss", "mss"),
            _package_check("pywin32", "win32gui"),
            _package_check("psutil", "psutil"),
            _package_check("paddleocr", "paddleocr", optional=True),
            _package_check("paddlepaddle", "paddle", optional=True),
            _package_check("rapidocr", "rapidocr", optional=True),
            EnvironmentCheck("ocr_provider", "ok", f"{config.ocr.provider} language={config.ocr.language} min_confidence={config.ocr.min_confidence}"),
            EnvironmentCheck("paddle_worker_mode", "ok", _paddle_worker_mode_detail()),
            EnvironmentCheck("paddle_timeout", "ok", _paddle_timeout_detail()),
            _path_check("paddle_cache", app_data_dir() / "ocr_cache" / "home", must_write=True),
            _path_check("data_dir", app_data_dir(), must_write=True),
            _path_check("config_dir", config_dir(), must_write=True),
            _path_check("database_path", database_path().parent, must_write=True),
            EnvironmentCheck("config_secret_storage", "ok", "API Key 保存到本地配置文件；诊断和导出会脱敏"),
        ]

    def format_text(self) -> str:
        return "\n".join(f"{item.key}={item.status} {item.detail}" for item in self.checks())


def _package_check(package_name: str, module_name: str, *, optional: bool = False) -> EnvironmentCheck:
    if util.find_spec(module_name) is None:
        return EnvironmentCheck(package_name, "optional" if optional else "missing", f"module {module_name} not found")
    try:
        version = metadata.version(package_name)
    except metadata.PackageNotFoundError:
        version = "installed"
    return EnvironmentCheck(package_name, "ok", version)


def _path_check(key: str, path: Path, *, must_write: bool) -> EnvironmentCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if must_write:
            probe = path / ".whochat_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
    except OSError as exc:
        return EnvironmentCheck(key, "error", f"{path} ({exc})")
    return EnvironmentCheck(key, "ok", str(path))


def _paddle_worker_mode_detail() -> str:
    import os

    return os.environ.get("WHOCHAT_PADDLEOCR_WORKER_MODE", "daemon")


def _paddle_timeout_detail() -> str:
    import os

    return f"{os.environ.get('WHOCHAT_PADDLEOCR_TIMEOUT_SECONDS', '90')}s"
