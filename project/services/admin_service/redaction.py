from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any


_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "license",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "cookie",
    "dsn",
)
_PATH_KEYS = {"path", "absolute_path", "local_path", "project_root", "evidence_path"}
_SAFE_POLICY_KEYS = {"token_persistent", "license_confirmed_by_operator"}
_WINDOWS_PATH = re.compile(r"(?i)(?:^|\s)[a-z]:[\\/][^\s,;\]\[{}]+")
_UNC_PATH = re.compile(r"(?i)(?:^|\s)\\\\[^\s,;\]\[{}]+")
_FILE_URL = re.compile(r"(?i)file://\S+")
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")


def sanitize_admin_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if is_sensitive_key(key):
                continue
            result[key] = sanitize_admin_value(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [sanitize_admin_value(item) for item in value]
    if isinstance(value, str):
        return redact_admin_text(value)
    return value


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SAFE_POLICY_KEYS:
        return False
    return (
        lowered in _PATH_KEYS
        or lowered.endswith("_path")
        or any(part in lowered for part in _SENSITIVE_KEY_PARTS)
    )


def redact_admin_text(value: str) -> str:
    text = str(value)
    for env_name in (
        "ADMIN_CONTROL_CENTER_TOKEN",
        "ADMIN_CONFIG_WRITE_TOKEN",
        "ADMIN_FEATURE_FLAGS_TOKEN",
        "RAG_API_KEY",
    ):
        secret = os.getenv(env_name, "").strip()
        if secret:
            text = text.replace(secret, "[redacted_secret]")
    text = _BEARER.sub("Bearer [redacted_secret]", text)
    text = _FILE_URL.sub("[redacted_local_path]", text)
    text = _WINDOWS_PATH.sub(" [redacted_local_path]", text)
    text = _UNC_PATH.sub(" [redacted_local_path]", text)
    return text[:2000]


def contains_sensitive_output(value: Any) -> bool:
    text = str(value)
    return bool(_WINDOWS_PATH.search(text) or _UNC_PATH.search(text) or _FILE_URL.search(text))


__all__ = ["contains_sensitive_output", "redact_admin_text", "sanitize_admin_value"]
