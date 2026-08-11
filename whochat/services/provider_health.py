from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from whochat.core.paths import app_data_dir


@dataclass(frozen=True)
class ProviderHealthSnapshot:
    status: str = "healthy"
    consecutive_failures: int = 0
    backoff_until: str | None = None
    updated_at: str | None = None


class ProviderHealthStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "state" / "ai_provider_health.json"

    def load(self) -> ProviderHealthSnapshot:
        if not self.path.exists():
            return ProviderHealthSnapshot()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ProviderHealthSnapshot()
        return ProviderHealthSnapshot(
            status=str(data.get("status", "healthy")) or "healthy",
            consecutive_failures=max(0, int(data.get("consecutive_failures", 0) or 0)),
            backoff_until=_optional_str(data.get("backoff_until")),
            updated_at=_optional_str(data.get("updated_at")),
        )

    def save(self, snapshot: ProviderHealthSnapshot) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(snapshot)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path


def provider_health_snapshot(status: str, failures: int, backoff_until: datetime | None) -> ProviderHealthSnapshot:
    return ProviderHealthSnapshot(
        status=status,
        consecutive_failures=max(0, failures),
        backoff_until=backoff_until.isoformat() if backoff_until else None,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def _optional_str(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
