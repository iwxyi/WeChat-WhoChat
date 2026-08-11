from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_DIAGNOSTIC_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"sk-[A-Za-z0-9_-]{12,}", "密钥"),
    (r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer"),
    (r"(?i)(Authorization\s*[:=]\s*)([^\s,;\"']{8,})", "认证头"),
    (r"(?i)(api[_-]?key\s*[=:]\s*[\"']?)([^\"'\s,;]{8,})", "API Key"),
    (r"(?i)(\"api[_-]?key\"\s*:\s*\")([^\"]{8,})(\")", "API Key"),
    (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "邮箱"),
    (r"https?://[^\s\"']+", "链接"),
    (r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", "手机号"),
    (r"(?<!\d)\d{12,}(?!\d)", "长数字"),
)


def redact_diagnostics_text(value: str) -> str:
    redacted = value
    for pattern, label in _DIAGNOSTIC_PATTERNS:
        redacted = _replace(pattern, label, redacted)
    return redacted


def redact_diagnostics_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_diagnostics_text(value)
    if isinstance(value, Mapping):
        return {
            key: _redact_secret_value(key, item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_diagnostics_payload(item) for item in value]
    return value


def _redact_secret_value(key: Any, value: Any) -> Any:
    key_text = str(key).lower()
    if any(token in key_text for token in ("api_key", "apikey", "authorization", "bearer", "token", "secret", "password")):
        if isinstance(value, str) and value:
            return "[已脱敏:密钥]"
    return redact_diagnostics_payload(value)


def _replace(pattern: str, label: str, text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        if len(match.groups()) == 2 and label in {"认证头", "API Key"}:
            return f"{match.group(1)}[已脱敏:{label}]"
        if len(match.groups()) == 3 and label == "API Key":
            return f"{match.group(1)}[已脱敏:{label}]{match.group(3)}"
        return f"[已脱敏:{label}]"

    return re.sub(pattern, repl, text)
