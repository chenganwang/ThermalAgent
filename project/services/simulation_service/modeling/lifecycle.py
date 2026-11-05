from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Iterator, Mapping
from uuid import uuid4

from .compiler import GeneratedModelArtifactStore, ModelCompiler
from .generated_model_metadata import (
    DEFAULT_EPHEMERAL_TTL_SECONDS,
    GENERATED_MODEL_ORIGINS,
    GENERATED_MODEL_RETENTIONS,
    capability_signature,
    derive_display_name,
    derive_model_summary,
    normalize_origin,
    normalize_retention,
    sanitize_display_name,
)
from .model_ir import ModelIR
from .registry import ComponentRegistry
from .synthesizer import ModelSynthesizer, RuleBasedModelSynthesizer
from .validator import ModelValidationError, ModelValidator


GENERATED_MODEL_STATUSES = frozenset({
    "draft", "validation_failed", "compiled", "pending_approval", "approved",
    "enabled", "disabled", "rejected", "execution_failed",
})
_SAFE_GENERATION_ID = re.compile(r"^gen_[a-f0-9]{32}$")
_TRANSITIONS = {
    "draft": frozenset({"validation_failed", "compiled", "rejected"}),
    "validation_failed": frozenset({"draft", "rejected"}),
    "compiled": frozenset({"pending_approval"}),
    "pending_approval": frozenset({"approved", "rejected"}),
    "approved": frozenset({"enabled", "rejected"}),
    "enabled": frozenset({"disabled", "execution_failed"}),
    "disabled": frozenset({"enabled", "rejected"}),
    "execution_failed": frozenset({"enabled", "disabled", "rejected"}),
    "rejected": frozenset(),
}
_IMMUTABLE_AFTER_CREATE = frozenset({
    "generation_id", "requirement_hash", "requirement_summary", "model_ir", "model_ir_hash",
    "missing_parameters", "validation_report", "synthesizer", "created_at",
})
_EXECUTABLE_FIELD_TOKENS = frozenset({
    "matlab", "entrypoint", "entry_point", "script", "source_code", "code", "block_path",
    "filesystem_path", "absolute_path", "artifact_id", "command", "shell",
})
_LEASE_KINDS = frozenset({"execution", "compile", "job", "session"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


class GeneratedModelLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GeneratedModelRepository:
    """Host-local append-only engineering revisions plus independent lifecycle metadata."""

    _coordination_lock = RLock()
    _model_locks: dict[tuple[str, str], RLock] = {}
    _activity: dict[tuple[str, str], dict[str, int]] = {}
    _sessions: dict[tuple[str, str], set[str]] = {}
    _deleting: set[tuple[str, str]] = set()

    def __init__(self, root: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self.root = (Path(root) if root is not None else project_root / "runtime" / "generated_models" / "records").resolve()
        self._lock = RLock()

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        generation_id = f"gen_{uuid4().hex}"
        now = _now()
        raw = deepcopy(dict(payload))
        origin = normalize_origin(raw.get("origin"))
        retention = normalize_retention(raw.get("retention"), origin=origin)
        ttl_seconds = max(0, int(raw.pop("ephemeral_ttl_seconds", DEFAULT_EPHEMERAL_TTL_SECONDS)))
        model_ir = raw.get("model_ir") if isinstance(raw.get("model_ir"), Mapping) else {}
        try:
            display_name = sanitize_display_name(raw.get("display_name")) if raw.get("display_name") else derive_display_name(model_ir)
        except ValueError as exc:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_NAME_INVALID", str(exc)) from exc
        record = {
            **raw,
            "generation_id": generation_id,
            "revision": 1,
            "metadata_revision": 1,
            "origin": origin,
            "retention": retention,
            "display_name": display_name,
            "description": str(raw.get("description") or derive_model_summary(model_ir))[:1000],
            "model_description": derive_model_summary(model_ir),
            "capability_signature": capability_signature(model_ir),
            "retention_ttl_seconds": ttl_seconds,
            "expires_at": (datetime.fromisoformat(now) + timedelta(seconds=ttl_seconds)).isoformat() if retention == "ephemeral" else None,
            "promoted_by": None,
            "promoted_at": None,
            "last_used_at": None,
            "last_executed_at": None,
            "last_execution_at": None,
            "last_activity_at": now,
            "use_count": 0,
            "deleted": False,
            "deleted_at": None,
            "deleted_by": None,
            "deletion_reason": None,
            "artifact_cleanup": None,
            "status": "draft",
            "artifact_id": None,
            "compilation": None,
            "approved_by": None,
            "approved_at": None,
            "enabled_by": None,
            "enabled_at": None,
            "disabled_by": None,
            "disabled_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
            "last_actor_id": None,
            "transition_reason": "candidate_created",
            "metadata_updated_by": None,
            "metadata_updated_at": now,
            "created_at": now,
            "updated_at": now,
        }
        self._write(generation_id, [record])
        return _public_record(record)

    def transition(
        self,
        generation_id: str,
        status: str,
        *,
        actor_id: str | None = None,
        reason: str = "",
        updates: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = self._id(generation_id)
        target = str(status or "").strip()
        if target not in GENERATED_MODEL_STATUSES:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_STATUS_INVALID", "Unknown generated-model status.")
        with self._model_lock(normalized):
            revisions = self._read(normalized)
            current = _normalize_record(revisions[-1])
            self._require_live(current)
            if target not in _TRANSITIONS.get(str(current.get("status")), frozenset()):
                raise GeneratedModelLifecycleError(
                    "GENERATED_MODEL_TRANSITION_INVALID",
                    f"Cannot transition generated model from {current.get('status')} to {target}.",
                )
            changes = deepcopy(dict(updates or {}))
            if _IMMUTABLE_AFTER_CREATE.intersection(changes):
                raise GeneratedModelLifecycleError("GENERATED_MODEL_IMMUTABLE_FIELD", "Immutable generation fields cannot change.")
            now = _now()
            record = {
                **deepcopy(current), **changes,
                "revision": int(current["revision"]) + 1,
                "status": target,
                "last_actor_id": str(actor_id or "")[:200] or None,
                "transition_reason": str(reason or "")[:500],
                "updated_at": now,
            }
            _apply_activity(record, now)
            if target == "approved":
                record.update({"approved_by": record["last_actor_id"], "approved_at": now})
            elif target == "enabled":
                record.update({"enabled_by": record["last_actor_id"], "enabled_at": now, "disabled_by": None, "disabled_at": None})
            elif target == "disabled":
                record.update({"disabled_by": record["last_actor_id"], "disabled_at": now})
            elif target == "rejected":
                record.update({"rejected_by": record["last_actor_id"], "rejected_at": now, "rejection_reason": str(reason or "")[:500]})
            revisions.append(record)
            self._write(normalized, revisions)
            return _public_record(record)

    def update_metadata(
        self,
        generation_id: str,
        *,
        actor_id: str,
        display_name: str | None = None,
        description: str | None = None,
        retention: str | None = None,
        ttl_seconds: int = DEFAULT_EPHEMERAL_TTL_SECONDS,
    ) -> dict[str, Any]:
        normalized = self._id(generation_id)
        with self._model_lock(normalized):
            revisions = self._read(normalized)
            current = _normalize_record(revisions[-1])
            self._require_live(current)
            changes: dict[str, Any] = {}
            if display_name is not None:
                try:
                    changes["display_name"] = sanitize_display_name(display_name)
                except ValueError as exc:
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_NAME_INVALID", str(exc)) from exc
            if description is not None:
                changes["description"] = str(description).strip()[:1000]
            if retention is not None:
                normalized_retention = str(retention).strip().casefold()
                if normalized_retention not in GENERATED_MODEL_RETENTIONS:
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_RETENTION_INVALID", "Unknown generated-model retention policy.")
                changes["retention"] = normalized_retention
                changes["expires_at"] = (
                    (datetime.now(timezone.utc) + timedelta(seconds=max(0, int(ttl_seconds)))).isoformat()
                    if normalized_retention == "ephemeral" else None
                )
            if not changes or all(current.get(key) == value for key, value in changes.items()):
                return _public_record(current)
            now = _now()
            if changes.get("retention") == "resident" and current.get("retention") != "resident":
                changes["promoted_by"] = str(actor_id or "")[:200] or None
                changes["promoted_at"] = now
                changes["last_activity_at"] = now
            revisions[-1] = {
                **deepcopy(current), **changes,
                "metadata_revision": int(current.get("metadata_revision") or 1) + 1,
                "metadata_updated_by": str(actor_id or "")[:200] or None,
                "metadata_updated_at": now,
                "updated_at": now,
            }
            self._write(normalized, revisions)
            return _public_record(revisions[-1])

    def append_engineering_revision(
        self,
        generation_id: str,
        *,
        actor_id: str,
        reason: str,
        model_ir: Mapping[str, Any],
        model_ir_hash: str,
        validation_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = self._id(generation_id)
        with self._model_lock(normalized):
            revisions = self._read(normalized)
            current = _normalize_record(revisions[-1])
            self._require_live(current)
            if self.has_active_activity(normalized):
                raise GeneratedModelLifecycleError("GENERATED_MODEL_IN_USE", "Generated model has an active operation.")
            now = _now()
            engineering = {
                **deepcopy(current),
                "revision": int(current["revision"]) + 1,
                "status": "draft",
                "model_ir": deepcopy(dict(model_ir)),
                "model_ir_hash": str(model_ir_hash),
                "validation_report": deepcopy(dict(validation_report)),
                "missing_parameters": [],
                "synthesis_status": "admin_edited",
                "artifact_id": None,
                "compilation": None,
                "approved_by": None,
                "approved_at": None,
                "enabled_by": None,
                "enabled_at": None,
                "disabled_by": None,
                "disabled_at": None,
                "rejected_by": None,
                "rejected_at": None,
                "rejection_reason": None,
                "model_description": derive_model_summary(model_ir),
                "capability_signature": capability_signature(model_ir),
                "last_actor_id": str(actor_id or "")[:200] or None,
                "transition_reason": str(reason or "engineering_revision_created")[:500],
                "updated_at": now,
            }
            _apply_activity(engineering, now)
            revisions.append(engineering)
            self._write(normalized, revisions)
            return _public_record(engineering)

    def record_use(self, generation_id: str, *, executed: bool) -> dict[str, Any]:
        normalized = self._id(generation_id)
        with self._model_lock(normalized):
            revisions = self._read(normalized)
            current = _normalize_record(revisions[-1])
            self._require_live(current)
            now = _now()
            current["last_used_at"] = now
            current["last_activity_at"] = now
            current["use_count"] = int(current.get("use_count") or 0) + 1
            if executed:
                current["last_executed_at"] = now
                current["last_execution_at"] = now
            _apply_activity(current, now)
            current["updated_at"] = now
            revisions[-1] = current
            self._write(normalized, revisions)
            return _public_record(current)

    def tombstone(
        self,
        generation_id: str,
        *,
        actor_id: str,
        reason: str,
        artifact_cleanup: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = self._id(generation_id)
        revisions = self._read(normalized)
        current = _normalize_record(revisions[-1])
        if current.get("deleted"):
            return _public_record(current)
        now = _now()
        current.update({
            "deleted": True,
            "deleted_at": now,
            "deleted_by": str(actor_id or "")[:200] or None,
            "deletion_reason": str(reason or "")[:500],
            "artifact_cleanup": deepcopy(dict(artifact_cleanup)),
            "updated_at": now,
        })
        revisions[-1] = current
        self._write(normalized, revisions)
        return _public_record(current)

    def get(self, generation_id: str, *, include_deleted: bool = False) -> dict[str, Any]:
        record = _normalize_record(self._read(self._id(generation_id))[-1])
        if record.get("deleted") and not include_deleted:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETED", "Generated model has been deleted.")
        return _public_record(record)

    def history(self, generation_id: str) -> list[dict[str, Any]]:
        return [_public_record(_normalize_record(item)) for item in self._read(self._id(generation_id))]

    def list(
        self,
        *,
        status: str | None = None,
        query: str | None = None,
        origin: str | None = None,
        retention: str | None = None,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if self.root.is_dir():
            for path in self.root.glob("gen_*.json"):
                try:
                    revisions = json.loads(path.read_text(encoding="utf-8")).get("revisions")
                except (OSError, json.JSONDecodeError, AttributeError):
                    continue
                if isinstance(revisions, list) and revisions and isinstance(revisions[-1], dict):
                    item = _public_record(_normalize_record(revisions[-1]))
                    if include_deleted or not item.get("deleted"):
                        items.append(item)
        if status:
            items = [item for item in items if item["status"] == status]
        if origin:
            items = [item for item in items if item.get("origin") == origin]
        if retention:
            items = [item for item in items if item.get("retention") == retention]
        keyword = str(query or "").strip().casefold()
        if keyword:
            items = [
                item for item in items
                if keyword in " ".join((
                    str(item.get("display_name") or ""), str(item.get("generation_id") or ""),
                    str(item.get("description") or ""), str(item.get("model_description") or ""),
                    str(item.get("requirement_summary") or ""),
                )).casefold()
            ]
        items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {
            "items": items, "total": len(items), "persistence": "host_local_file_backed",
            "revision_policy": "append_only_engineering_revisions",
        }

    @contextmanager
    def activity_lease(self, generation_id: str, kind: str) -> Iterator[dict[str, Any]]:
        normalized = self._id(generation_id)
        lease_kind = str(kind or "").strip().casefold()
        if lease_kind not in _LEASE_KINDS:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_LEASE_INVALID", "Unknown generated-model lease kind.")
        key = self._key(normalized)
        lock = self._model_lock(normalized)
        with lock:
            with self._coordination_lock:
                if key in self._deleting:
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETE_IN_PROGRESS", "Generated model deletion is in progress.")
                current = self.get(normalized, include_deleted=True)
                if current.get("deleted"):
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETED", "Generated model has been deleted.")
                kinds = self._activity.setdefault(key, {})
                kinds[lease_kind] = kinds.get(lease_kind, 0) + 1
        try:
            yield current
        finally:
            with self._coordination_lock:
                kinds = self._activity.get(key, {})
                if kinds.get(lease_kind, 0) <= 1:
                    kinds.pop(lease_kind, None)
                else:
                    kinds[lease_kind] -= 1
                if not kinds:
                    self._activity.pop(key, None)

    def has_active_activity(self, generation_id: str) -> bool:
        key = self._key(self._id(generation_id))
        with self._coordination_lock:
            return any(value > 0 for value in self._activity.get(key, {}).values()) or bool(self._sessions.get(key))

    def activity_snapshot(self, generation_id: str) -> dict[str, int]:
        key = self._key(self._id(generation_id))
        with self._coordination_lock:
            result = dict(self._activity.get(key, {}))
            if self._sessions.get(key):
                result["session"] = len(self._sessions[key])
            return result

    def register_session_reference(self, generation_id: str, session_id: str) -> None:
        normalized = self._id(generation_id)
        session = str(session_id or "").strip()
        if not session:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_SESSION_INVALID", "Session identifier is required.")
        key = self._key(normalized)
        with self._model_lock(normalized):
            with self._coordination_lock:
                if key in self._deleting:
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETE_IN_PROGRESS", "Generated model deletion is in progress.")
                current = self.get(normalized, include_deleted=True)
                if current.get("deleted"):
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETED", "Generated model has been deleted.")
                self._sessions.setdefault(key, set()).add(session[:200])

    def release_session_reference(self, generation_id: str, session_id: str) -> None:
        normalized = self._id(generation_id)
        key = self._key(normalized)
        with self._coordination_lock:
            sessions = self._sessions.get(key)
            if not sessions:
                return
            sessions.discard(str(session_id or "").strip()[:200])
            if not sessions:
                self._sessions.pop(key, None)

    @contextmanager
    def deletion_guard(self, generation_id: str) -> Iterator[dict[str, Any]]:
        normalized = self._id(generation_id)
        key = self._key(normalized)
        lock = self._model_lock(normalized)
        with lock:
            current = self.get(normalized, include_deleted=True)
            if current.get("deleted"):
                yield current
                return
            with self._coordination_lock:
                if any(value > 0 for value in self._activity.get(key, {}).values()) or self._sessions.get(key):
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_IN_USE", "Generated model has an active execution, job, compile, or session.")
                if key in self._deleting:
                    raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETE_IN_PROGRESS", "Generated model deletion is already in progress.")
                self._deleting.add(key)
            try:
                yield current
            finally:
                with self._coordination_lock:
                    self._deleting.discard(key)

    def _read(self, generation_id: str) -> list[dict[str, Any]]:
        path = self._path(generation_id)
        if not path.is_file():
            raise GeneratedModelLifecycleError("GENERATED_MODEL_NOT_FOUND", "Generated model was not found.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            revisions = payload["revisions"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_STORAGE_CORRUPT", "Generated-model record is unreadable.") from exc
        if not isinstance(revisions, list) or not revisions or not all(isinstance(item, dict) for item in revisions):
            raise GeneratedModelLifecycleError("GENERATED_MODEL_STORAGE_CORRUPT", "Generated-model revisions are malformed.")
        return revisions

    def _write(self, generation_id: str, revisions: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(generation_id)
        temporary = path.with_suffix(".json.tmp")
        payload = {"schema_version": 2, "generation_id": generation_id, "revisions": revisions}
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with self._lock:
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(path)

    def _path(self, generation_id: str) -> Path:
        path = (self.root / f"{generation_id}.json").resolve()
        if not path.is_relative_to(self.root):
            raise GeneratedModelLifecycleError("GENERATED_MODEL_ID_INVALID", "Generation ID escaped storage.")
        return path

    def _key(self, generation_id: str) -> tuple[str, str]:
        return (str(self.root), generation_id)

    def _model_lock(self, generation_id: str) -> RLock:
        key = self._key(generation_id)
        with self._coordination_lock:
            return self._model_locks.setdefault(key, RLock())

    @staticmethod
    def _require_live(record: Mapping[str, Any]) -> None:
        if record.get("deleted"):
            raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETED", "Generated model has been deleted.")

    @staticmethod
    def _id(generation_id: str) -> str:
        value = str(generation_id or "").strip()
        if not _SAFE_GENERATION_ID.fullmatch(value):
            raise GeneratedModelLifecycleError("GENERATED_MODEL_ID_INVALID", "Invalid generation ID.")
        return value


class GeneratedModelService:
    def __init__(
        self,
        *,
        repository: GeneratedModelRepository | None = None,
        registry: ComponentRegistry | None = None,
        synthesizer: ModelSynthesizer | None = None,
        artifact_store: GeneratedModelArtifactStore | None = None,
        ephemeral_ttl_seconds: int = DEFAULT_EPHEMERAL_TTL_SECONDS,
    ) -> None:
        self.repository = repository or GeneratedModelRepository()
        self.registry = registry or ComponentRegistry.default()
        self.synthesizer = synthesizer or RuleBasedModelSynthesizer(self.registry)
        self.validator = ModelValidator(self.registry)
        self.artifact_store = artifact_store or GeneratedModelArtifactStore()
        self.ephemeral_ttl_seconds = max(0, int(ephemeral_ttl_seconds))

    def create_candidate(
        self,
        requirement: str,
        *,
        origin: str = "llm_generated",
        retention: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        text = str(requirement or "").strip()
        normalized_origin = str(origin or "").strip().casefold()
        if normalized_origin not in GENERATED_MODEL_ORIGINS:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_ORIGIN_INVALID", "Unknown generated-model origin.")
        if retention is not None and str(retention).strip().casefold() not in GENERATED_MODEL_RETENTIONS:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_RETENTION_INVALID", "Unknown generated-model retention policy.")
        synthesis = self.synthesizer.synthesize(text)
        model_ir = synthesis.model_ir
        if model_ir is None:
            report: dict[str, Any] = {
                "valid": False,
                "issues": [{"code": "SYNTHESIS_UNSUPPORTED", "message": "No reviewed component vocabulary was recognized."}],
                "normalized_parameters": {},
            }
        else:
            report = self.validator.validate(model_ir).to_dict()
        return self.repository.create({
            "requirement_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "requirement_summary": text[:500],
            "model_ir": model_ir.to_dict() if model_ir else None,
            "model_ir_hash": model_ir.digest() if model_ir else None,
            "capability_signature": capability_signature(model_ir.to_dict() if model_ir else None),
            "missing_parameters": list(synthesis.missing_parameters),
            "validation_report": report,
            "synthesizer": synthesis.synthesizer,
            "synthesis_status": synthesis.status,
            "warnings": list(synthesis.warnings),
            "origin": normalized_origin,
            "retention": retention,
            "display_name": display_name,
            "ephemeral_ttl_seconds": self.ephemeral_ttl_seconds,
        })

    def compile_candidate(self, generation_id: str, compiler: ModelCompiler) -> dict[str, Any]:
        with self.repository.activity_lease(generation_id, "compile"):
            current = self.repository.get(generation_id)
            if current["status"] != "draft" or current.get("missing_parameters") or not (current.get("validation_report") or {}).get("valid"):
                raise GeneratedModelLifecycleError("GENERATED_MODEL_NOT_VALIDATED", "Only a complete, valid draft can compile.")
            model_ir = ModelIR.from_dict(current.get("model_ir") or {})
            try:
                validated = self.validator.validate_for_compilation(model_ir)
            except ModelValidationError:
                return self.repository.transition(generation_id, "validation_failed", reason="validation_failed_before_compile")
            result = compiler.compile(validated)
            if result.status != "compiled" or not result.artifact_id:
                return self.repository.transition(
                    generation_id, "validation_failed", reason="compiler_failed", updates={"compilation": result.to_dict()},
                )
            compiled = self.repository.transition(
                generation_id, "compiled", reason="deterministic_compilation_succeeded",
                updates={"artifact_id": result.artifact_id, "compilation": result.to_dict()},
            )
            return self.repository.transition(compiled["generation_id"], "pending_approval", reason="awaiting_admin_review")

    def update_metadata(
        self,
        generation_id: str,
        *,
        actor_id: str,
        display_name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        if display_name is None and description is None:
            raise GeneratedModelLifecycleError("GENERATED_MODEL_METADATA_INVALID", "At least one metadata field is required.")
        return self.repository.update_metadata(
            generation_id, actor_id=actor_id, display_name=display_name, description=description,
            ttl_seconds=self.ephemeral_ttl_seconds,
        )

    def create_engineering_revision(
        self,
        generation_id: str,
        model_ir: Mapping[str, Any],
        *,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any]:
        if not isinstance(model_ir, Mapping):
            raise GeneratedModelLifecycleError("GENERATED_MODEL_ENGINEERING_EDIT_INVALID", "Model IR must be an object.")
        forbidden = _find_executable_field(model_ir)
        if forbidden:
            raise GeneratedModelLifecycleError(
                "GENERATED_MODEL_EXECUTABLE_FIELD_FORBIDDEN",
                f"Executable implementation field is forbidden in Model IR: {forbidden}.",
            )
        candidate = ModelIR.from_dict(model_ir)
        report = self.validator.validate(candidate).to_dict()
        if not report.get("valid"):
            raise GeneratedModelLifecycleError("GENERATED_MODEL_ENGINEERING_EDIT_INVALID", "Edited Model IR did not pass the deterministic validator.")
        return self.repository.append_engineering_revision(
            generation_id, actor_id=actor_id, reason=reason, model_ir=candidate.to_dict(),
            model_ir_hash=candidate.digest(), validation_report=report,
        )

    def promote(self, generation_id: str, *, actor_id: str) -> dict[str, Any]:
        current = self.repository.get(generation_id)
        if current.get("retention") == "resident":
            return current
        return self.repository.update_metadata(
            generation_id, actor_id=actor_id, retention="resident", ttl_seconds=self.ephemeral_ttl_seconds,
        )

    def approve(self, generation_id: str, *, actor_id: str, reason: str) -> dict[str, Any]:
        current = self.repository.get(generation_id)
        if current["status"] == "approved":
            return current
        return self.repository.transition(generation_id, "approved", actor_id=actor_id, reason=reason)

    def reject(self, generation_id: str, *, actor_id: str, reason: str) -> dict[str, Any]:
        if not str(reason or "").strip():
            raise GeneratedModelLifecycleError("GENERATED_MODEL_REJECTION_REASON_REQUIRED", "A rejection reason is required.")
        return self.repository.transition(generation_id, "rejected", actor_id=actor_id, reason=reason)

    def enable(self, generation_id: str, *, actor_id: str) -> dict[str, Any]:
        current = self.repository.get(generation_id)
        if current["status"] == "enabled":
            return current
        if current["status"] not in {"approved", "disabled", "execution_failed"}:
            return self.repository.transition(
                generation_id, "enabled", actor_id=actor_id, reason="enabled_for_confirmed_execution",
            )
        if current.get("retention") != "resident":
            raise GeneratedModelLifecycleError("GENERATED_MODEL_RESIDENCY_REQUIRED", "Only resident generated models can be enabled for reuse.")
        return self.repository.transition(generation_id, "enabled", actor_id=actor_id, reason="enabled_for_confirmed_execution")

    def disable(self, generation_id: str, *, actor_id: str) -> dict[str, Any]:
        current = self.repository.get(generation_id)
        if current["status"] == "disabled":
            return current
        return self.repository.transition(generation_id, "disabled", actor_id=actor_id, reason="disabled_by_operator")

    def mark_execution_failed(self, generation_id: str, *, reason: str) -> dict[str, Any]:
        return self.repository.transition(generation_id, "execution_failed", reason=reason)

    def delete(
        self,
        generation_id: str,
        *,
        actor_id: str,
        reason: str,
        active_jobs: bool = False,
    ) -> dict[str, Any]:
        with self.repository.deletion_guard(generation_id) as current:
            if current.get("deleted"):
                return {
                    "generation_id": generation_id, "deleted": True, "idempotent": True,
                    "deleted_at": current.get("deleted_at"), "artifact_cleanup": current.get("artifact_cleanup"),
                }
            if current.get("status") == "enabled":
                raise GeneratedModelLifecycleError("GENERATED_MODEL_DELETE_ENABLED", "Enabled generated models must be disabled before deletion.")
            if active_jobs:
                raise GeneratedModelLifecycleError("GENERATED_MODEL_IN_USE", "Generated model has an active Admin job.")
            artifact_ids = list(dict.fromkeys(
                str(item.get("artifact_id"))
                for item in self.repository.history(generation_id)
                if item.get("artifact_id")
            ))
            removed_ids = [artifact_id for artifact_id in artifact_ids if self.artifact_store.delete(artifact_id)]
            cleanup = {
                "artifact_id": str(current.get("artifact_id") or "") or None,
                "artifact_ids": artifact_ids,
                "removed_artifact_ids": removed_ids,
                "removed": len(removed_ids) == len(artifact_ids) if artifact_ids else False,
                "resolver": "controlled_artifact_id",
            }
            tombstone = self.repository.tombstone(
                generation_id, actor_id=actor_id, reason=reason, artifact_cleanup=cleanup,
            )
            return {
                "generation_id": generation_id, "display_name": tombstone.get("display_name"),
                "deleted": True, "idempotent": False, "deleted_at": tombstone.get("deleted_at"),
                "artifact_cleanup": cleanup,
            }

    def find_enabled_by_requirement(self, requirement: str) -> dict[str, Any] | None:
        text = str(requirement or "").strip()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        synthesis = self.synthesizer.synthesize(text)
        signature = None
        if synthesis.model_ir is not None and not synthesis.missing_parameters:
            report = self.validator.validate(synthesis.model_ir)
            if report.valid:
                signature = capability_signature(synthesis.model_ir.to_dict())
        for item in self.repository.list(status="enabled", retention="resident")["items"]:
            same_capability = bool(signature and item.get("capability_signature") == signature)
            if (item.get("requirement_hash") == digest or same_capability) and item.get("execution_eligible"):
                matched = dict(item)
                matched["_reuse_match"] = "requirement_hash" if item.get("requirement_hash") == digest else "capability_match"
                return matched
        return None


def _find_executable_field(value: Any, path: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().casefold()
            current_path = f"{path}.{key}" if path else str(key)
            if normalized in _EXECUTABLE_FIELD_TOKENS or any(token in normalized for token in ("matlab", "filesystem", "block_path")):
                return current_path
            nested = _find_executable_field(child, current_path)
            if nested:
                return nested
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            nested = _find_executable_field(child, f"{path}[{index}]")
            if nested:
                return nested
    return None


def _normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    item = deepcopy(dict(record))
    origin = normalize_origin(item.get("origin"))
    retention = normalize_retention(item.get("retention"), origin=origin)
    model_ir = item.get("model_ir") if isinstance(item.get("model_ir"), Mapping) else {}
    item["origin"] = origin
    item["retention"] = retention
    item["display_name"] = item.get("display_name") or derive_display_name(model_ir)
    item["model_description"] = item.get("model_description") or derive_model_summary(model_ir)
    item["capability_signature"] = item.get("capability_signature") or capability_signature(model_ir)
    item["description"] = item.get("description") or item["model_description"]
    item["metadata_revision"] = int(item.get("metadata_revision") or 1)
    item["metadata_updated_at"] = item.get("metadata_updated_at") or item.get("updated_at") or item.get("created_at")
    item["metadata_updated_by"] = item.get("metadata_updated_by")
    item["promoted_by"] = item.get("promoted_by")
    item["promoted_at"] = item.get("promoted_at")
    item["last_used_at"] = item.get("last_used_at")
    item["last_executed_at"] = item.get("last_executed_at")
    item["last_execution_at"] = item.get("last_execution_at") or item.get("last_executed_at")
    item["last_activity_at"] = item.get("last_activity_at") or item.get("updated_at") or item.get("created_at")
    item["retention_ttl_seconds"] = max(1, int(item.get("retention_ttl_seconds") or DEFAULT_EPHEMERAL_TTL_SECONDS))
    item["use_count"] = int(item.get("use_count") or 0)
    item["deleted"] = bool(item.get("deleted"))
    item["deleted_at"] = item.get("deleted_at")
    item["deleted_by"] = item.get("deleted_by")
    item["deletion_reason"] = item.get("deletion_reason")
    item["artifact_cleanup"] = item.get("artifact_cleanup")
    if retention == "resident":
        item["expires_at"] = None
    elif not item.get("expires_at"):
        activity = _parse_time(item.get("last_activity_at")) or datetime.now(timezone.utc)
        item["expires_at"] = (activity + timedelta(seconds=item["retention_ttl_seconds"])).isoformat()
    return item


def _apply_activity(record: dict[str, Any], now: str) -> None:
    record["last_activity_at"] = now
    if record.get("retention") == "ephemeral":
        ttl_seconds = max(1, int(record.get("retention_ttl_seconds") or DEFAULT_EPHEMERAL_TTL_SECONDS))
        record["expires_at"] = (datetime.fromisoformat(now) + timedelta(seconds=ttl_seconds)).isoformat()
    else:
        record["expires_at"] = None


def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
    item = _normalize_record(record)
    model_ir = item.get("model_ir") if isinstance(item.get("model_ir"), dict) else {}
    components = model_ir.get("components") if isinstance(model_ir.get("components"), list) else []
    connections = model_ir.get("connections") if isinstance(model_ir.get("connections"), list) else []
    item["execution_eligible"] = bool(
        not item.get("deleted") and item.get("status") == "enabled" and item.get("approved_at")
        and item.get("retention") == "resident" and item.get("artifact_id")
    )
    item["model_summary"] = {
        "model_id": model_ir.get("model_id"),
        "domain": model_ir.get("model_domain"),
        "component_count": len(components),
        "connection_count": len(connections),
        "component_types": list(dict.fromkeys(str(component.get("type") or "") for component in components if isinstance(component, dict))),
        "components": [
            {
                "id": str(component.get("id") or ""), "type": str(component.get("type") or ""),
                "parameters": {
                    str(name): {"value": value.get("value"), "unit": str(value.get("unit") or "")}
                    for name, value in (component.get("parameters") or {}).items() if isinstance(value, dict)
                },
            }
            for component in components if isinstance(component, dict)
        ],
        "topology": [
            {
                "from_component": edge.get("from_component"), "from_port": edge.get("from_port"),
                "to_component": edge.get("to_component"), "to_port": edge.get("to_port"),
            }
            for edge in connections if isinstance(edge, dict)
        ],
        "requested_outputs": [
            {key: output.get(key) for key in ("id", "type", "source_component_id", "source_port") if output.get(key) not in (None, "")}
            for output in (model_ir.get("requested_outputs") or []) if isinstance(output, dict)
        ],
    }
    return item


__all__ = [
    "GENERATED_MODEL_STATUSES", "GeneratedModelLifecycleError", "GeneratedModelRepository",
    "GeneratedModelService",
]
