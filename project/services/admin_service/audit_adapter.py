from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from services.simulation_service.feature_flags import feature_flag_audit_path
from services.simulation_service.model_assets.config import load_model_asset_config

from .actions.audit import action_audit_path
from .config.history import config_audit_path
from .contracts import AdminAPIError
from .redaction import sanitize_admin_value


class LegacyAuditAdapter:
    """Read-only adapter over legacy logs plus central Config and Action sources."""

    def __init__(self, project_root: Path, *, max_source_lines: int = 1000) -> None:
        self.project_root = project_root
        self.max_source_lines = max(1, min(max_source_lines, 5000))

    def list_events(self, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        page_size = max(1, min(int(limit), 200))
        offset = _decode_cursor(cursor)
        events, sources = self._load_all()
        page = events[offset : offset + page_size]
        next_offset = offset + len(page)
        return {
            "items": page,
            "next_cursor": _encode_cursor(next_offset) if next_offset < len(events) else None,
            "returned": len(page),
            "source_event_count": len(events),
            "sources": sources,
            "partial": True,
            "read_only": True,
        }

    def get_event(self, audit_id: str) -> dict[str, Any]:
        events, _sources = self._load_all()
        for event in events:
            if event.get("audit_id") == audit_id:
                return event
        raise AdminAPIError(
            "AUDIT_NOT_FOUND",
            "Audit event was not found.",
            status_code=404,
            details={"audit_id": audit_id},
        )

    def _load_all(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        paths = self._source_paths()
        events: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for source, path in paths:
            records, readable = self._read_jsonl(path)
            sources.append({"source": source, "available": path.is_file(), "readable": readable})
            for ordinal, raw in records:
                event = self._normalize(source, raw, ordinal)
                if event is not None:
                    events.append(event)
        events.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return events, sources

    def _source_paths(self) -> tuple[tuple[str, Path], ...]:
        feature_path = feature_flag_audit_path(self.project_root)
        model_path = load_model_asset_config(self.project_root).audit_path
        config_path = config_audit_path(self.project_root)
        action_path = action_audit_path(self.project_root)
        return (
            ("action_registry", action_path),
            ("config_registry_jsonl", config_path),
            ("feature_flags_jsonl", feature_path),
            ("model_assets_jsonl", model_path),
        )

    def _read_jsonl(self, path: Path) -> tuple[list[tuple[int, dict[str, Any]]], bool]:
        if not path.is_file():
            return [], True
        lines: deque[tuple[int, str]] = deque(maxlen=self.max_source_lines)
        try:
            with path.open("r", encoding="utf-8") as handle:
                for ordinal, line in enumerate(handle, start=1):
                    if len(line) <= 65536:
                        lines.append((ordinal, line))
        except OSError:
            return [], False
        records: list[tuple[int, dict[str, Any]]] = []
        for ordinal, line in lines:
            try:
                raw = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(raw, dict):
                records.append((ordinal, raw))
        return records, True

    def _normalize(self, source: str, raw: dict[str, Any], ordinal: int) -> dict[str, Any] | None:
        if source == "action_registry":
            timestamp = str(raw.get("at") or "")
            event = {
                "audit_id": _audit_id(source, raw, ordinal),
                "timestamp": timestamp,
                "actor_id": str(raw.get("actor_id") or "system"),
                "actor_role": str(raw.get("actor_type") or "system"),
                "action": str(raw.get("action") or "action.unknown"),
                "target_type": "action",
                "target_id": str(raw.get("action_id") or "unknown"),
                "invocation_id": raw.get("invocation_id"),
                "permission": raw.get("permission"),
                "previous_value": None,
                "new_value": raw.get("result_summary"),
                "success": bool(raw.get("success", False)),
                "status": str(raw.get("status") or "failed"),
                "reason": "read_only_action_invocation",
                "request_id": raw.get("request_id"),
                "job_id": None,
                "risk_level": str(raw.get("risk_level") or "low"),
                "dry_run": bool(raw.get("dry_run", False)),
                "duration_ms": raw.get("duration_ms"),
                "parameters_summary": raw.get("parameters_summary"),
                "error_code": raw.get("error_code"),
                "sensitive_fields_redacted": True,
                "source": source,
            }
        elif source == "config_registry_jsonl":
            timestamp = str(raw.get("at") or "")
            keys = [str(item) for item in raw.get("keys") or ()]
            event = {
                "audit_id": _audit_id(source, raw, ordinal),
                "timestamp": timestamp,
                "actor_id": str(raw.get("actor_id") or "system"),
                "actor_role": str(raw.get("actor_role") or "system"),
                "auth_source": str(raw.get("auth_source") or "unknown"),
                "action": str(raw.get("action") or "config.unknown"),
                "target_type": "config",
                "target_id": ",".join(keys) or "runtime_feature_flags",
                "previous_value": raw.get("diff"),
                "new_value": raw.get("diff"),
                "success": bool(raw.get("success", False)),
                "reason": str(raw.get("reason") or ""),
                "request_id": raw.get("request_id"),
                "job_id": None,
                "risk_level": "medium",
                "previous_version": raw.get("previous_version"),
                "new_version": raw.get("new_version"),
                "dry_run": bool(raw.get("dry_run", False)),
                "no_change": bool(raw.get("no_change", False)),
                "error_code": raw.get("error_code"),
                "sensitive_fields_redacted": True,
                "source": source,
            }
        elif source == "feature_flags_jsonl":
            timestamp = str(raw.get("at") or "")
            action_name = str(raw.get("action") or "unknown")
            target_id = ",".join(str(item) for item in raw.get("changed_fields") or ()) or "runtime_feature_flags"
            event = {
                "audit_id": _audit_id(source, raw, ordinal),
                "timestamp": timestamp,
                "actor_id": str(raw.get("actor") or "legacy_admin"),
                "actor_role": "legacy_shared_token",
                "action": f"feature_flags.{action_name}",
                "target_type": "config",
                "target_id": target_id,
                "previous_value": raw.get("previous_flags"),
                "new_value": raw.get("new_flags"),
                "success": True,
                "reason": "legacy_feature_flag_event",
                "request_id": None,
                "job_id": None,
                "risk_level": "medium",
                "sensitive_fields_redacted": True,
                "source": source,
            }
        else:
            timestamp = str(raw.get("timestamp") or "")
            event = {
                "audit_id": _audit_id(source, raw, ordinal),
                "timestamp": timestamp,
                "actor_id": str(raw.get("actor_type") or "system"),
                "actor_role": str(raw.get("actor_type") or "system"),
                "action": f"model_asset.{raw.get('action') or 'unknown'}",
                "target_type": "model_asset",
                "target_id": str(raw.get("asset_id") or "unknown"),
                "previous_value": raw.get("previous_status"),
                "new_value": raw.get("new_status"),
                "success": bool(raw.get("success", True)),
                "reason": str(raw.get("reason") or ""),
                "request_id": None,
                "job_id": None,
                "risk_level": "high",
                "sensitive_fields_redacted": True,
                "source": source,
            }
        if not _valid_timestamp(timestamp):
            event["timestamp"] = ""
        return sanitize_admin_value(event)


def _audit_id(source: str, raw: dict[str, Any], ordinal: int) -> str:
    existing = str(raw.get("event_id") or "").strip()
    material = f"{source}:{existing or ordinal}:{raw.get('at') or raw.get('timestamp') or ''}"
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:20]
    return f"audit-{digest}"


def _valid_timestamp(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        offset = int(base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise AdminAPIError("REQUEST_INVALID", "Audit cursor is invalid.", status_code=422) from exc
    if offset < 0:
        raise AdminAPIError("REQUEST_INVALID", "Audit cursor is invalid.", status_code=422)
    return offset


__all__ = ["LegacyAuditAdapter"]
