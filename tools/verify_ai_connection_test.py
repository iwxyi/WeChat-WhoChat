from __future__ import annotations

import io
import json
import os
import shutil
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "ai_connection_test_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import whochat.ai.generator as generator_module
from whochat.ai.generator import test_ai_connection
from whochat.app import create_app
from whochat.config import AppConfig
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


class FakeResponse:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def main() -> int:
    config = AppConfig()
    config.ai.provider = "OpenAI Compatible"
    config.ai.base_url = "https://api.example.test/v1"
    config.ai.model = "verify-model"
    config.ai.api_key = "sk-connection-test-secret-value"
    calls = {"count": 0, "payload": "", "auth": "", "auths": [], "urls": []}
    original_urlopen = generator_module.urllib.request.urlopen

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        calls["payload"] = request.data.decode("utf-8")
        calls["urls"].append(request.full_url)
        auth = request.get_header("Authorization", "") or dict(request.header_items()).get("Authorization", "")
        calls["auth"] = auth
        calls["auths"].append(auth)
        if calls["count"] == 1:
            return FakeResponse({"choices": [{"message": {"content": "{\"ok\":true}"}}]})
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"bad key","api_key":"sk-should-not-log"}'),
        )

    generator_module.urllib.request.urlopen = fake_urlopen
    try:
        ok = test_ai_connection(config)
        failed = test_ai_connection(config)
        local_config = AppConfig()
        local_config.ai.provider = "Local Preview"
        local = test_ai_connection(local_config)
        app = create_app()
        window = MainWindow(build_services())
        window._ai_provider.setCurrentText("OpenAI Compatible")
        window._ai_base_url.setText("https://api.example.test/v1")
        window._ai_model.setText("verify-model")
        window._ai_api_key.setText("sk-ui-connection-test-secret")
        window._test_ai_settings()
        window._ai_base_url.setText("https://api.example.test/v1/chat/completions")
        window._test_ai_settings()
        window.close()
        app.quit()
    finally:
        generator_module.urllib.request.urlopen = original_urlopen

    if not ok.ok or ok.status != "ok":
        raise RuntimeError(f"expected connection test success, got {ok}")
    if failed.ok or failed.status != "http_error:401":
        raise RuntimeError(f"expected connection test HTTP failure, got {failed}")
    if "认证失败" not in failed.detail or "API Key" not in failed.detail:
        raise RuntimeError(f"401 failure should explain API key/provider mismatch: {failed.detail}")
    if not local.ok or local.status != "local_preview":
        raise RuntimeError(f"expected local preview no-network success, got {local}")
    if calls["count"] != 4:
        raise RuntimeError(f"expected four network calls including UI tests, got {calls['count']}")
    auths = "\n".join(calls["auths"])
    if "sk-connection-test-secret-value" not in auths or "sk-ui-connection-test-secret" not in auths:
        raise RuntimeError(f"connection test did not send configured API keys: {calls['auths']}")

    log_text = (DATA_DIR / "logs" / "ai_provider.log").read_text(encoding="utf-8")
    for forbidden in ["sk-connection-test-secret", "sk-ui-connection-test", "sk-should-not-log", "api_key"]:
        if forbidden in log_text:
            raise RuntimeError(f"connection diagnostics leaked sensitive content: {forbidden}")
    for expected in ["connection_test_ok", "connection_test_http_error:401"]:
        if expected not in log_text:
            raise RuntimeError(f"missing diagnostic status {expected}: {log_text}")
    if any(url.count("/chat/completions") != 1 for url in calls["urls"]):
        raise RuntimeError(f"endpoint should not duplicate chat/completions: {calls['urls']}")
    if window._ai_action_status is None or not window._ai_action_status.text():
        raise RuntimeError("AI action status should show test feedback")
    if "认证失败" not in window._ai_action_status.text():
        raise RuntimeError(f"UI should show actionable 401 feedback: {window._ai_action_status.text()}")
    print(f"calls={calls['count']} ok={ok.status} failed={failed.status} log_chars={len(log_text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
