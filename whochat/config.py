from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from whochat.core.paths import config_dir
from whochat.security.secrets import AI_API_KEY_NAME, SecretStore


@dataclass
class AIProviderConfig:
    provider: str = "OpenAI Compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    api_key: str = ""
    temperature: float = 0.7
    context_tokens: int = 16000
    timeout_seconds: int = 60
    request_cooldown_seconds: int = 8
    dedupe_context_minutes: int = 30
    max_daily_cloud_requests: int = 100
    failure_backoff_threshold: int = 3
    failure_backoff_minutes: int = 5


@dataclass
class PrivacyConfig:
    enable_long_term_memory: bool = True
    save_debug_screenshots: bool = False
    trim_context_for_cloud: bool = True
    require_cloud_prompt_review: bool = True
    manual_protection_blocks_replies: bool = True
    diagnostic_log_retention_days: int = 14
    debug_sample_retention_days: int = 14
    capture_retention_days: int = 7
    calibration_retention_days: int = 30
    reply_feedback_retention_days: int = 180


@dataclass
class OcrConfig:
    provider: str = "PaddleOCR"
    language: str = "ch"
    min_confidence: float = 0.5
    use_gpu: bool = False


@dataclass
class CaptureConfig:
    auto_capture_enabled: bool = True
    foreground_only: bool = True
    scroll_debounce_ms: int = 900
    ocr_min_interval_ms: int = 30000
    pause_ai_on_unknown_page: bool = True
    block_memory_for_unconfirmed_contact: bool = True


@dataclass
class FloatingConfig:
    placement_preference: str = "auto"
    opacity_percent: int = 96
    suggestion_count: int = 3


@dataclass
class TargetWindowConfig:
    app_id: str
    label: str
    enabled: bool
    process_names: list[str] = field(default_factory=list)
    title_keywords: list[str] = field(default_factory=list)
    exclude_title_keywords: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    ai: AIProviderConfig = field(default_factory=AIProviderConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    floating: FloatingConfig = field(default_factory=FloatingConfig)
    targets: list[TargetWindowConfig] = field(default_factory=list)


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()
        self.secrets = SecretStore()

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = AppConfig()
            config.targets = default_target_windows()
            config.ai.api_key = self.secrets.get(AI_API_KEY_NAME)
            return config
        data = json.loads(self.path.read_text(encoding="utf-8"))
        capture_data = _migrate_capture_config(data.get("capture", {}))
        config = AppConfig(
            ai=AIProviderConfig(**data.get("ai", {})),
            privacy=PrivacyConfig(**data.get("privacy", {})),
            ocr=OcrConfig(**data.get("ocr", {})),
            capture=CaptureConfig(**capture_data),
            floating=FloatingConfig(**data.get("floating", {})),
            targets=_load_targets(data.get("targets")),
        )
        secret = self.secrets.get(AI_API_KEY_NAME)
        if secret:
            config.ai.api_key = secret
        return config

    def save(self, config: AppConfig) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = asdict(config)
        secret_result = self.secrets.set(AI_API_KEY_NAME, config.ai.api_key)
        if secret_result.ok and secret_result.backend != "none":
            data["ai"]["api_key"] = ""
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return secret_result.backend


def default_config_path() -> Path:
    return config_dir() / "config.json"


def _migrate_capture_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    migrated = dict(value)
    if "foreground_only" not in migrated:
        migrated["foreground_only"] = True
    if "ocr_min_interval_ms" not in migrated:
        migrated["ocr_min_interval_ms"] = CaptureConfig.ocr_min_interval_ms
    if "auto_capture_enabled" in migrated and migrated["auto_capture_enabled"] is False and "foreground_only" not in value:
        migrated["auto_capture_enabled"] = True
    return migrated


def default_target_windows() -> list[TargetWindowConfig]:
    return [
        TargetWindowConfig(
            app_id="wechat",
            label="微信",
            enabled=True,
            process_names=["Weixin.exe", "WeChat.exe", "WeChatAppEx.exe"],
            title_keywords=["微信", "WeChat"],
            exclude_title_keywords=["图片和视频", "设置", "聊天记录", "转发", "发送给", "选择联系人"],
        ),
        TargetWindowConfig(
            app_id="telegram",
            label="Telegram",
            enabled=False,
            process_names=["Telegram.exe"],
            title_keywords=["Telegram"],
            exclude_title_keywords=[],
        ),
        TargetWindowConfig(
            app_id="generic_chat",
            label="通用聊天",
            enabled=False,
            process_names=[],
            title_keywords=[],
            exclude_title_keywords=[],
        ),
    ]


def _load_targets(value: Any) -> list[TargetWindowConfig]:
    if not isinstance(value, list):
        return default_target_windows()
    result: list[TargetWindowConfig] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            app_id = str(item.get("app_id", "")).strip()
            label = str(item.get("label", "")).strip() or app_id
            if not app_id:
                continue
            result.append(
                TargetWindowConfig(
                    app_id=app_id,
                    label=label,
                    enabled=bool(item.get("enabled", False)),
                    process_names=_string_list(item.get("process_names")),
                    title_keywords=_string_list(item.get("title_keywords")),
                    exclude_title_keywords=_string_list(item.get("exclude_title_keywords")),
                )
            )
        except TypeError:
            continue
    defaults = {target.app_id: target for target in default_target_windows()}
    merged = {target.app_id: target for target in result}
    for app_id, target in defaults.items():
        if app_id not in merged:
            merged[app_id] = target
        elif not merged[app_id].exclude_title_keywords:
            merged[app_id].exclude_title_keywords = list(target.exclude_title_keywords)
    return list(merged.values())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
