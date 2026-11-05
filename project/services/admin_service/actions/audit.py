from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Mapping
from uuid import uuid4

from services.admin_service.contracts import AdminAPIError

from .security import sanitize_action_value, summarize_parameters


_AUDIT_LOCK = Lock()


def action_audit_path(project_root: Path) -> Path:
    configured = os.getenv("ADMIN_ACTION_AUDIT_PATH", "runtime/config/admin_action_audit.jsonl").strip()
    path = Path(configured)
    return path if path.is_absolute() else project_root / path


class ActionAuditStore:
    def __init__(self, project_root: Path, *, path: Path | None = None) -> None:
        self.project_root = project_root
        self._path_override = path

    @property
    def path(self) -> Path:
        return self._path_override or action_audit_path(self.project_root)

    def record(
        self,
        *,
        invocation_id: str,
        action_id: str,
        actor_id: str,
        actor_type: str,
        permission: str,
        risk_level: str,
        dry_run: bool,
        success: bool,
        status: str,
        request_id: str,
        started_at: str,
        duration_ms: int,
        parameters: Mapping[str, Any],
        result_summary: Mapping[str, Any] | None,
        error_code: str | None,
    ) -> None:
        event = sanitize_action_value(
            {
                "event_id": f"action-audit-{uuid4().hex}",
                "at": datetime.now(timezone.utc).isoformat(),
                "source": "action_registry",
                "action": "action.dry_run" if dry_run else "action.invoke",
                "invocation_id": invocation_id,
                "action_id": action_id,
                "actor_id": actor_id,
                "actor_type": actor_type,
                "permission": permission,
                "risk_level": risk_level,
                "dry_run": dry_run,
                "success": success,
                "status": status,
                "request_id": request_id,
                "started_at": started_at,
                "duration_ms": max(0, int(duration_ms)),
                "parameters_summary": summarize_parameters(parameters),
                "result_summary": sanitize_action_value(dict(result_summary or {})),
                "error_code": error_code,
                "sensitive_fields_redacted": True,
            }
        )
        try:
            path = self.path
            with _AUDIT_LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError as exc:
            raise AdminAPIError(
                "ADMIN_ACTION_AUDIT_FAILED",
                "Action audit could not be persisted.",
                status_code=503,
            ) from exc


__all__ = ["ActionAuditStore", "action_audit_path"]
