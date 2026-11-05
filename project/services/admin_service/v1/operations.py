from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from ..contracts import AdminAPIError
from ..redaction import is_sensitive_key, redact_admin_text, sanitize_admin_value


JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})
JOB_TYPES = frozenset({
    "document_preflight", "document_dry_run", "document_commit", "document_ingestion",
    "page_reparse", "chunk_revision_index_update", "document_index_update",
    "index_candidate_build", "index_validation", "index_release",
    "model_validation", "model_smoke", "model_smoke_test",
    "generated_model_compile", "generated_model_smoke",
    "generated_model_instrumentation", "generated_model_execution", "generated_result_critique",
})
_SAFE_JOB_ID = re.compile(r"^job-[a-f0-9]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdminJobStore:
    """Host-local durable job receipts; this is not a distributed queue."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._lock = RLock()

    def create(self, *, job_type: str, resource_type: str, resource_id: str, actor_id: str) -> dict[str, Any]:
        normalized_type = str(job_type or "").strip()
        if normalized_type not in JOB_TYPES:
            raise AdminAPIError("JOB_TYPE_INVALID", "Unsupported Admin job type.", status_code=422)
        now = _now()
        job = {
            "job_id": f"job-{uuid4().hex}",
            "type": normalized_type,
            "resource_type": str(resource_type or "resource")[:80],
            "resource_id": str(resource_id or "")[:200],
            "resource": {
                "type": str(resource_type or "resource")[:80],
                "id": str(resource_id or "")[:200],
            },
            "actor_id": str(actor_id or "admin")[:200],
            "status": "queued",
            "progress": 0,
            "message": "Queued",
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "result": None,
            "error_code": None,
            "error": None,
            "persistence": "host_local_file_backed",
            "durable_queue": False,
        }
        return self._save(job)

    def start(self, job_id: str, *, progress: int = 0, message: str = "Running") -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] not in {"queued", "running"}:
            raise AdminAPIError("JOB_TRANSITION_INVALID", "Only queued jobs can start.", status_code=409)
        job.update({"status": "running", "progress": _progress(progress), "message": str(message)[:500], "started_at": job.get("started_at") or _now()})
        return self._save(job)

    def succeed(self, job_id: str, *, result: Mapping[str, Any] | None = None, message: str = "Succeeded") -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] == "succeeded":
            return job
        if job["status"] not in {"queued", "running"}:
            raise AdminAPIError("JOB_TRANSITION_INVALID", "Job cannot succeed from its current state.", status_code=409)
        return self._finish(job, status="succeeded", result=dict(result or {}), error_code=None, message=message)

    def fail(self, job_id: str, *, error_code: str, message: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] == "failed":
            return job
        if job["status"] not in {"queued", "running"}:
            raise AdminAPIError("JOB_TRANSITION_INVALID", "Job cannot fail from its current state.", status_code=409)
        return self._finish(job, status="failed", result=None, error_code=str(error_code or "JOB_FAILED")[:120], message=message)

    def cancel(self, job_id: str, *, message: str = "Cancelled") -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] == "cancelled":
            return job
        if job["status"] not in {"queued", "running"}:
            raise AdminAPIError("JOB_TRANSITION_INVALID", "Completed jobs cannot be cancelled.", status_code=409)
        return self._finish(job, status="cancelled", result=None, error_code=None, message=message)

    def get(self, job_id: str) -> dict[str, Any]:
        normalized = self._validate_id(job_id)
        path = self._path(normalized)
        if not path.is_file():
            raise AdminAPIError("JOB_NOT_FOUND", "Admin job was not found.", status_code=404)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise AdminAPIError("JOB_STORAGE_CORRUPT", "Admin job record is unreadable.", status_code=500) from exc
        return sanitize_admin_value(value)

    def list(self, *, job_type: str | None = None, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if self.root.is_dir():
            for path in self.root.glob("job-*.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(item, dict):
                    continue
                if job_type and item.get("type") != job_type:
                    continue
                if status and item.get("status") != status:
                    continue
                items.append(sanitize_admin_value(item))
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        maximum = max(1, min(int(limit), 500))
        return {"items": items[:maximum], "total": len(items), "persistence": "host_local_file_backed", "durable_queue": False}

    def cancel_active_for_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
        job_types: set[str] | frozenset[str],
        message: str,
    ) -> list[str]:
        cancelled: list[str] = []
        for job in self.list(limit=500)["items"]:
            if job.get("resource_type") != resource_type or job.get("resource_id") != resource_id:
                continue
            if job.get("type") not in job_types or job.get("status") not in {"queued", "running"}:
                continue
            try:
                result = self.cancel(str(job["job_id"]), message=message)
            except AdminAPIError as exc:
                if exc.code == "JOB_TRANSITION_INVALID":
                    continue
                raise
            cancelled.append(str(result["job_id"]))
        return cancelled

    def _finish(self, job: dict[str, Any], *, status: str, result: Any, error_code: str | None, message: str) -> dict[str, Any]:
        finished = _now()
        started = job.get("started_at") or job.get("created_at")
        job.update({
            "status": status,
            "progress": 100 if status == "succeeded" else int(job.get("progress") or 0),
            "message": str(message)[:500],
            "started_at": started,
            "finished_at": finished,
            "duration_ms": _duration_ms(started, finished),
            "result": sanitize_admin_value(result),
            "error_code": error_code,
            "error": {"code": error_code, "message": str(message)[:500]} if error_code else None,
        })
        return self._save(job)

    def _save(self, job: Mapping[str, Any]) -> dict[str, Any]:
        item = sanitize_admin_value(dict(job))
        job_id = self._validate_id(str(item.get("job_id") or ""))
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(job_id)
        temporary = path.with_suffix(".json.tmp")
        with self._lock:
            temporary.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
        return dict(item)

    def _path(self, job_id: str) -> Path:
        return (self.root / f"{job_id}.json").resolve()

    @staticmethod
    def _validate_id(job_id: str) -> str:
        value = str(job_id or "").strip()
        if not _SAFE_JOB_ID.fullmatch(value):
            raise AdminAPIError("JOB_ID_INVALID", "Invalid Admin job identifier.", status_code=422)
        return value


class AdminAuditStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self._lock = RLock()

    def append(
        self,
        *,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        before: Any,
        after: Any,
        result: str,
        request_id: str | None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        event = _audit_sanitize({
            "event_id": f"admin-event-{uuid4().hex}",
            "timestamp": _now(),
            "actor_id": str(actor_id or "admin")[:200],
            "action": str(action or "UNKNOWN")[:120],
            "resource_type": str(resource_type or "resource")[:80],
            "resource_id": str(resource_id or "")[:200],
            "before": before,
            "after": after,
            "result": str(result or "unknown")[:40],
            "error_code": str(error_code)[:120] if error_code else None,
            "request_id": str(request_id)[:128] if request_id else None,
            "sensitive_fields_redacted": True,
        })
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                handle.flush()
        return event

    def list(self, *, limit: int = 100, action: str | None = None) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(item, dict) and (not action or item.get("action") == action):
                    items.append(sanitize_admin_value(item))
        items.reverse()
        maximum = max(1, min(int(limit), 500))
        return {"items": items[:maximum], "total": len(items), "append_only": True}


_GENERATED_OPERATION_JOB_TYPES = {
    "INSTRUMENT_GENERATED_MODEL": "generated_model_instrumentation",
    "EXECUTE_GENERATED_MODEL": "generated_model_execution",
    "CRITIQUE_GENERATED_RESULT": "generated_result_critique",
}


class GeneratedModelOperationRecorder:
    """Write bounded generated-model stage receipts through existing Admin stores."""

    def __init__(self, jobs: AdminJobStore, audit: AdminAuditStore) -> None:
        self.jobs = jobs
        self.audit = audit

    def record(
        self,
        action: str,
        generation_id: str,
        *,
        status: str,
        summary: Mapping[str, Any],
        error_code: str | None = None,
    ) -> None:
        normalized_action = str(action or "").strip().upper()
        job_type = _GENERATED_OPERATION_JOB_TYPES.get(normalized_action)
        if job_type is None:
            raise AdminAPIError("GENERATED_OPERATION_INVALID", "Unsupported generated-model operation.", status_code=422)
        bounded = _bounded_generated_summary(summary)
        actor_id = "thermalagent-runtime"
        job = self.jobs.create(
            job_type=job_type,
            resource_type="generated_model",
            resource_id=generation_id,
            actor_id=actor_id,
        )
        self.jobs.start(job["job_id"], progress=90, message=f"{normalized_action} recorded")
        succeeded = str(status or "").casefold() == "success"
        if succeeded:
            self.jobs.succeed(job["job_id"], result=bounded, message=f"{normalized_action} completed")
        else:
            self.jobs.fail(
                job["job_id"],
                error_code=str(error_code or "GENERATED_OPERATION_FAILED")[:120],
                message=f"{normalized_action} failed",
            )
        self.audit.append(
            actor_id=actor_id,
            action=normalized_action,
            resource_type="generated_model",
            resource_id=generation_id,
            before=None,
            after=bounded,
            result="success" if succeeded else "failed",
            error_code=error_code,
            request_id=None,
        )


def _progress(value: int) -> int:
    return max(0, min(int(value), 99))


def _bounded_generated_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    forbidden = {"series", "raw", "raw_workspace", "workspace", "simulation_output"}

    def visit(item: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "[TRUNCATED]"
        if isinstance(item, Mapping):
            return {
                str(key)[:80]: visit(child, depth + 1)
                for key, child in list(item.items())[:40]
                if str(key).casefold() not in forbidden
            }
        if isinstance(item, (list, tuple, set)):
            return [visit(child, depth + 1) for child in list(item)[:40]]
        if isinstance(item, str):
            return item[:500]
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return str(type(item).__name__)[:80]

    bounded = visit(value)
    return bounded if isinstance(bounded, dict) else {}


def _audit_sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(str(key)) else _audit_sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_audit_sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_admin_text(value)
    return value


def _duration_ms(started: str | None, finished: str) -> int | None:
    if not started:
        return None
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((end - start).total_seconds() * 1000))


__all__ = [
    "AdminAuditStore", "AdminJobStore", "GeneratedModelOperationRecorder",
    "JOB_STATUSES", "JOB_TYPES",
]
