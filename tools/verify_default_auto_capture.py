from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "default_auto_capture_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from whochat.config import ConfigStore
from whochat.services.bootstrap import build_services


def main() -> int:
    config = ConfigStore().load()
    if not config.capture.auto_capture_enabled:
        raise RuntimeError("default config should enable automatic OCR capture")
    if config.capture.ocr_min_interval_ms != 5000:
        raise RuntimeError(f"default OCR flow interval should be 5000ms, got {config.capture.ocr_min_interval_ms}")
    services = build_services()
    if not services.autocapture.enabled:
        raise RuntimeError("services should start auto capture enabled by default")
    legacy_config = DATA_DIR / "config" / "legacy.json"
    legacy_config.parent.mkdir(parents=True, exist_ok=True)
    legacy_config.write_text(
        '{"capture":{"auto_capture_enabled":false,"scroll_debounce_ms":500,"pause_ai_on_unknown_page":true}}',
        encoding="utf-8",
    )
    migrated = ConfigStore(legacy_config).load()
    if not migrated.capture.auto_capture_enabled or not migrated.capture.foreground_only:
        raise RuntimeError(f"legacy capture config should migrate to automatic OCR defaults: {migrated.capture}")
    legacy_interval_config = DATA_DIR / "config" / "legacy_interval.json"
    legacy_interval_config.write_text(
        '{"capture":{"ocr_min_interval_ms":30000,"auto_capture_enabled":false,"scroll_debounce_ms":500,"pause_ai_on_unknown_page":true}}',
        encoding="utf-8",
    )
    migrated_interval = ConfigStore(legacy_interval_config).load()
    if migrated_interval.capture.ocr_min_interval_ms != 5000:
        raise RuntimeError(f"legacy 30000ms OCR interval should migrate to 5000ms: {migrated_interval.capture}")
    print(
        f"auto_capture={config.capture.auto_capture_enabled} foreground_only={config.capture.foreground_only} "
        f"ocr_interval={config.capture.ocr_min_interval_ms}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
