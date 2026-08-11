from __future__ import annotations

from dataclasses import dataclass


SERVICE_NAME = "WhoChat"
AI_API_KEY_NAME = "ai_api_key"


@dataclass(frozen=True)
class SecretResult:
    ok: bool
    backend: str
    message: str


class SecretStore:
    def get(self, name: str) -> str:
        try:
            return _WindowsCredentialStore().get(name)
        except Exception:
            return ""

    def set(self, name: str, value: str) -> SecretResult:
        if not value:
            return SecretResult(True, "none", "empty secret skipped")
        try:
            _WindowsCredentialStore().set(name, value)
            return SecretResult(True, "windows_credential_manager", "secret saved")
        except Exception as exc:
            return SecretResult(False, "unavailable", str(exc))


class _WindowsCredentialStore:
    def _target(self, name: str) -> str:
        return f"{SERVICE_NAME}:{name}"

    def get(self, name: str) -> str:
        import win32cred

        try:
            credential = win32cred.CredRead(self._target(name), win32cred.CRED_TYPE_GENERIC)
        except Exception:
            return ""
        blob = credential.get("CredentialBlob")
        if isinstance(blob, bytes):
            return blob.decode("utf-16-le", errors="ignore").rstrip("\x00")
        return str(blob or "")

    def set(self, name: str, value: str) -> None:
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": self._target(name),
                "UserName": SERVICE_NAME,
                "CredentialBlob": value,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )

