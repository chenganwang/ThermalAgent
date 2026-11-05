from __future__ import annotations

from datetime import datetime, timezone
import os
from threading import Event, RLock, Thread
from typing import Any

from .compiler import GeneratedModelArtifactStore
from .generated_model_metadata import DEFAULT_EPHEMERAL_TTL_SECONDS
from .lifecycle import GeneratedModelLifecycleError, GeneratedModelService


GC_REASON_EXPIRED = "GENERATED_MODEL_EPHEMERAL_TTL_EXPIRED"
DEFAULT_JANITOR_INTERVAL_SECONDS = 60 * 60
DEFAULT_JANITOR_BATCH_SIZE = 50


def _positive_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return max(1, int(raw)) if raw else default
    except ValueError:
        return default


class GeneratedModelJanitor:
    """Bounded host-local cleanup for expired, idle LLM-generated ephemeral models."""

    def __init__(
        self,
        service: GeneratedModelService,
        *,
        artifact_store: GeneratedModelArtifactStore | None = None,
        ttl_seconds: int | None = None,
        interval_seconds: int | None = None,
        batch_size: int | None = None,
        job_store: Any | None = None,
        audit_store: Any | None = None,
    ) -> None:
        self.service = service
        self.artifact_store = artifact_store or service.artifact_store
        self.ttl_seconds = max(1, int(ttl_seconds or _positive_env("GENERATED_MODEL_EPHEMERAL_TTL_SECONDS", DEFAULT_EPHEMERAL_TTL_SECONDS)))
        self.interval_seconds = max(1, int(interval_seconds or _positive_env("GENERATED_MODEL_JANITOR_INTERVAL_SECONDS", DEFAULT_JANITOR_INTERVAL_SECONDS)))
        self.batch_size = max(1, min(int(batch_size or _positive_env("GENERATED_MODEL_JANITOR_BATCH_SIZE", DEFAULT_JANITOR_BATCH_SIZE)), 500))
        self.job_store = job_store
        self.audit_store = audit_store
        self._stop = Event()
        self._thread: Thread | None = None
        self._run_lock = RLock()
        self.last_result: dict[str, Any] | None = None

    def sweep(
        self,
        *,
        dry_run: bool,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        observed = now or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        maximum = max(1, min(int(limit or self.batch_size), 500))
        with self._run_lock:
            candidates: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for item in self.service.repository.list()["items"]:
                decision = self._decision(item, observed)
                public = {
                    "generation_id": item.get("generation_id"),
                    "display_name": item.get("display_name"),
                    "origin": item.get("origin"),
                    "retention": item.get("retention"),
                    "status": item.get("status"),
                    "expires_at": item.get("expires_at"),
                    "last_activity_at": item.get("last_activity_at"),
                    "reason_code": decision,
                }
                if decision == GC_REASON_EXPIRED:
                    candidates.append(public)
                elif decision.startswith("SKIP_ACTIVE"):
                    skipped.append(public)
            candidates.sort(key=lambda item: str(item.get("expires_at") or ""))
            bounded = candidates[:maximum]
            deleted_ids: list[str] = []
            failures: list[dict[str, str]] = []
            if not dry_run:
                # The candidate decision list is the mandatory preview used by this exact sweep.
                for candidate in bounded:
                    generation_id = str(candidate["generation_id"])
                    try:
                        result = self.service.delete(
                            generation_id,
                            actor_id="generated-model-janitor",
                            reason=GC_REASON_EXPIRED,
                            active_jobs=self._has_active_job(generation_id),
                        )
                    except GeneratedModelLifecycleError as exc:
                        failures.append({"generation_id": generation_id, "error_code": exc.code})
                        continue
                    if result.get("deleted"):
                        deleted_ids.append(generation_id)
            result = {
                "dry_run": bool(dry_run),
                "preview_performed": True,
                "observed_at": observed.isoformat(),
                "ttl_seconds": self.ttl_seconds,
                "reason_code": GC_REASON_EXPIRED,
                "candidate_count": len(candidates),
                "bounded_candidate_count": len(bounded),
                "candidates": bounded,
                "skipped_active": skipped,
                "deleted_count": len(deleted_ids),
                "deleted_generation_ids": deleted_ids,
                "failures": failures,
            }
            self.last_result = result
            self._audit(result)
            return result

    def start(self) -> dict[str, Any]:
        if self._thread is not None and self._thread.is_alive():
            return {
                "started": True,
                "idempotent": True,
                "startup_sweep": "scheduled",
                "last_result": self.last_result,
            }
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="generated-model-janitor", daemon=True)
        self._thread.start()
        return {
            "started": True,
            "idempotent": False,
            "startup_sweep": "scheduled",
            "batch_size": self.batch_size,
        }

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=min(5.0, float(self.interval_seconds)))
        self._thread = None

    def _loop(self) -> None:
        if not self._stop.is_set():
            try:
                self.sweep(dry_run=False, limit=self.batch_size)
            except Exception:
                # Startup must stay available; the periodic loop retries later.
                pass
        while not self._stop.wait(self.interval_seconds):
            try:
                self.sweep(dry_run=False, limit=self.batch_size)
            except Exception:
                # The API lifecycle remains available; the next bounded interval retries.
                continue

    def _decision(self, item: dict[str, Any], now: datetime) -> str:
        generation_id = str(item.get("generation_id") or "")
        if item.get("origin") != "llm_generated":
            return "SKIP_ORIGIN"
        if item.get("retention") != "ephemeral":
            return "SKIP_RESIDENT"
        if item.get("status") == "enabled":
            return "SKIP_ENABLED"
        if self.service.repository.has_active_activity(generation_id):
            return "SKIP_ACTIVE_LEASE"
        if self._has_active_job(generation_id):
            return "SKIP_ACTIVE_JOB"
        expires_at = _parse_time(item.get("expires_at"))
        if expires_at is None:
            return "SKIP_EXPIRY_UNKNOWN"
        return GC_REASON_EXPIRED if expires_at <= now else "SKIP_NOT_EXPIRED"

    def _has_active_job(self, generation_id: str) -> bool:
        list_jobs = getattr(self.job_store, "list", None)
        if not callable(list_jobs):
            return False
        try:
            items = list_jobs(limit=500).get("items", [])
        except Exception:
            # Unavailable activity evidence fails closed for cleanup.
            return True
        return any(
            item.get("resource_type") == "generated_model"
            and item.get("resource_id") == generation_id
            and item.get("status") in {"queued", "running"}
            for item in items if isinstance(item, dict)
        )

    def _audit(self, result: dict[str, Any]) -> None:
        append = getattr(self.audit_store, "append", None)
        if not callable(append):
            return
        try:
            if not result["dry_run"]:
                candidates = {item["generation_id"]: item for item in result["candidates"]}
                for generation_id in result["deleted_generation_ids"]:
                    item = candidates.get(generation_id, {})
                    append(
                        actor_id="generated-model-janitor",
                        action="AUTO_DELETE_EXPIRED_GENERATED_MODEL",
                        resource_type="generated_model",
                        resource_id=generation_id,
                        before={
                            "display_name": item.get("display_name"),
                            "last_activity_at": item.get("last_activity_at"),
                            "ttl_seconds": result["ttl_seconds"],
                        },
                        after={"deleted": True, "reason_code": result["reason_code"]},
                        result="success", error_code=None, request_id=None,
                    )
            append(
                actor_id="generated-model-janitor",
                action="PREVIEW_GENERATED_MODEL_GC" if result["dry_run"] else "CLEANUP_EXPIRED_GENERATED_MODELS",
                resource_type="generated_model_collection",
                resource_id="ephemeral",
                before=None,
                after={
                    "reason_code": result["reason_code"],
                    "candidate_count": result["candidate_count"],
                    "deleted_count": result["deleted_count"],
                    "deleted_generation_ids": result["deleted_generation_ids"],
                    "failure_count": len(result["failures"]),
                },
                result="success" if not result["failures"] else "partial",
                error_code=None if not result["failures"] else "GENERATED_MODEL_GC_PARTIAL",
                request_id=None,
            )
        except Exception:
            return


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "DEFAULT_JANITOR_BATCH_SIZE", "DEFAULT_JANITOR_INTERVAL_SECONDS", "GC_REASON_EXPIRED",
    "GeneratedModelJanitor",
]
