from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .errors import config_error


DEFAULT_CONFIG_STATE_PATH = Path("runtime/config/admin_config_registry_state.json")
DEFAULT_CONFIG_AUDIT_PATH = Path("runtime/config/admin_config_audit.jsonl")


def config_state_path(project_root: Path) -> Path:
    return _configured_path("ADMIN_CONFIG_STATE_PATH", DEFAULT_CONFIG_STATE_PATH, project_root, ".json")


def config_audit_path(project_root: Path) -> Path:
    return _configured_path("ADMIN_CONFIG_AUDIT_PATH", DEFAULT_CONFIG_AUDIT_PATH, project_root, ".jsonl")


class ConfigHistoryStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def load_state(self) -> dict[str, Any] | None:
        path = config_state_path(self.project_root)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise config_error(
                "ADMIN_CONFIG_HISTORY_INVALID",
                "Config Registry history is unavailable or invalid.",
                status_code=503,
            ) from exc
        if not isinstance(raw, dict):
            raise config_error(
                "ADMIN_CONFIG_HISTORY_INVALID",
                "Config Registry history is unavailable or invalid.",
                status_code=503,
            )
        return raw

    def write_state(self, state: Mapping[str, Any]) -> None:
        path = config_state_path(self.project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temp.write_text(
                json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise config_error(
                "ADMIN_CONFIG_APPLY_FAILED",
                "Config Registry state could not be committed atomically.",
                status_code=503,
            ) from exc

    def restore_state(self, original: Mapping[str, Any] | None) -> None:
        path = config_state_path(self.project_root)
        if original is None:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise config_error(
                    "ADMIN_CONFIG_ROLLBACK_FAILED",
                    "Config Registry transaction recovery failed.",
                    status_code=503,
                ) from exc
            return
        self.write_state(original)

    def append_audit(self, event: Mapping[str, Any]) -> None:
        path = config_audit_path(self.project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n"
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(record)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise config_error(
                "ADMIN_CONFIG_AUDIT_WRITE_FAILED",
                "Config audit could not be committed; the change was not kept.",
                status_code=503,
            ) from exc


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        value = int(base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise config_error(
            "REQUEST_INVALID",
            "Config history cursor is invalid.",
            status_code=422,
        ) from exc
    if value < 0:
        raise config_error("REQUEST_INVALID", "Config history cursor is invalid.", status_code=422)
    return value


def _configured_path(env_name: str, default: Path, project_root: Path, suffix: str) -> Path:
    raw = os.getenv(env_name, "").strip()
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = project_root / path
    if path.name in {".env", ".env.example"} or path.suffix.lower() != suffix:
        raise config_error(
            "ADMIN_CONFIG_STORAGE_MISCONFIGURED",
            "Config Registry storage is misconfigured.",
            status_code=503,
        )
    return path


__all__ = [
    "ConfigHistoryStore",
    "config_audit_path",
    "config_state_path",
    "decode_cursor",
    "encode_cursor",
]
