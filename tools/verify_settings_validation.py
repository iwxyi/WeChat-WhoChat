from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "settings_validation_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.ocr.engine import PreviewOcrEngine
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


class ShutdownPreview(PreviewOcrEngine):
    def __init__(self) -> None:
        self.closed = False

    def shutdown(self) -> None:
        self.closed = True


def main() -> int:
    app = create_app()
    services = build_services()
    window = MainWindow(services)
    window._select_page("settings")

    original_provider = window._config.ai.provider
    window._ai_provider.setCurrentText("OpenAI Compatible")
    window._ai_base_url.setText("not-a-url")
    window._ai_model.setText("verify-model")
    window._save_ai_settings()
    if window._config.ai.provider != original_provider:
        raise RuntimeError("invalid cloud base URL should not mutate config")
    if "http" not in window.statusBar().currentMessage():
        raise RuntimeError(f"invalid base URL did not surface actionable status: {window.statusBar().currentMessage()}")

    window._ai_base_url.setText("https://api.example.test/v1")
    window._ai_model.setText("")
    window._save_ai_settings()
    if "模型名称不能为空" not in window.statusBar().currentMessage():
        raise RuntimeError("empty cloud model should be rejected")

    window._ai_provider.setCurrentText("Local Model")
    window._ai_model.setText("")
    window._save_ai_settings()
    if "本地模型名称不能为空" not in window.statusBar().currentMessage():
        raise RuntimeError("empty local model should be rejected")

    window._ai_model.setText("local-verify")
    window._ocr_language.setText("")
    window._save_ai_settings()
    if "OCR 语言不能为空" not in window.statusBar().currentMessage():
        raise RuntimeError("empty OCR language should be rejected")

    window._ocr_language.setText("ch")
    for checkbox in window._target_checkboxes.values():
        checkbox.setChecked(False)
    window._save_ai_settings()
    if "至少启用一个目标聊天应用" not in window.statusBar().currentMessage():
        raise RuntimeError("all-disabled target windows should be rejected")

    window._target_checkboxes["wechat"].setChecked(True)
    old_engine = ShutdownPreview()
    services.pipeline.ocr_engine = old_engine
    window._save_ai_settings()
    if not old_engine.closed:
        raise RuntimeError("saving valid OCR settings should shut down previous OCR engine before switching")
    if window._config.ai.provider != "Local Model" or window._config.ai.model != "local-verify":
        raise RuntimeError("valid settings were not persisted into runtime config")

    print(f"provider={window._config.ai.provider} model={window._config.ai.model} old_ocr_closed={old_engine.closed}")
    window.close()
    services.shutdown()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
