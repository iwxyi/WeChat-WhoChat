from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["WHOCHAT_CONFIG_DIR"] = str(ROOT / "tmp" / "config_security")

from whochat.config import ConfigStore


def main() -> int:
    store = ConfigStore()
    config = store.load()
    config.ai.api_key = "whochat-secret-value"
    backend = store.save(config)
    raw = store.path.read_text(encoding="utf-8")
    if backend != "unavailable" and "whochat-secret-value" in raw:
        raise RuntimeError("API key leaked into config file while secure store was available")
    loaded = store.load()
    if backend != "unavailable" and loaded.ai.api_key != "whochat-secret-value":
        raise RuntimeError("API key was not restored from secure store")
    loaded.ai.api_key = ""
    clear_backend = store.save(loaded)
    cleared = store.load()
    if cleared.ai.api_key:
        raise RuntimeError("clearing API key should not restore a stale secure-store value")
    fallback_path = store.path.parent / "fallback.json"
    fallback_path.write_text(
        '{"ai":{"provider":"OpenAI Compatible","base_url":"https://fallback.example/v1","model":"fallback","api_key":"fallback-secret"}}',
        encoding="utf-8",
    )
    fallback = ConfigStore(fallback_path).load()
    if fallback.ai.api_key != "fallback-secret":
        raise RuntimeError("config-file fallback API key should not be overwritten by stale secure-store value")
    print(f"config={store.path}")
    print(f"secret_backend={backend}")
    print(f"clear_backend={clear_backend}")
    print(f"config_contains_secret={'whochat-secret-value' in raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
