from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping
from uuid import uuid4

from services.simulation_service.feature_flags import (
    FeatureFlagValidationError,
    feature_flag_runtime_path,
    validate_feature_flag_updates,
)

from ..redaction import redact_admin_text
from .diff import affected_modules, build_config_diff
from .errors import ConfigRegistryError, config_error
from .feature_flag_adapter import FeatureFlagCapture, FeatureFlagConfigAdapter
from .history import ConfigHistoryStore, decode_cursor, encode_cursor
from .registry import CONFIG_KEYS, CONFIG_REGISTRY, registered_config_schema
from .schemas import ConfigPatchRequest, ConfigRollbackRequest


_CONFIG_WRITE_LOCK = Lock()


@dataclass(frozen=True)
class ConfigActor:
    actor_id: str
    role: str
    auth_source: str


class ConfigRegistryService:
    """Single-process, versioned control plane for four runtime feature flags."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.adapter = FeatureFlagConfigAdapter(project_root)
        self.store = ConfigHistoryStore(project_root)

    def read_config(self) -> dict[str, Any]:
        with _CONFIG_WRITE_LOCK:
            state, capture, original = self._load_context()
        return {
            "registry": "runtime_feature_flags",
            "version": state["current_version"],
            "items": self._items(state, capture),
            "current_snapshot": dict(state["current_snapshot"]),
            "history_initialized": original is not None,
            "write_enabled": _env_true("ADMIN_CONFIG_WRITE_ENABLED"),
            "read_only_for_viewer": True,
            "side_effects": [],
        }

    def read_schema(self) -> dict[str, Any]:
        with _CONFIG_WRITE_LOCK:
            state, _capture, _original = self._load_context()
        return {
            "registry": "runtime_feature_flags",
            "version": state["current_version"],
            "items": registered_config_schema(),
            "additional_properties": False,
            "global_monotonic_version": True,
            "supported_operations": ["read", "dry_run", "apply", "history", "rollback"],
            "unsupported_operations": ["reload", "restart", "arbitrary_key", "env_edit"],
            "side_effects": [],
        }

    def read_history(self, *, limit: int, cursor: str | None) -> dict[str, Any]:
        page_size = max(1, min(int(limit), 200))
        offset = decode_cursor(cursor)
        with _CONFIG_WRITE_LOCK:
            state, _capture, _original = self._load_context()
        history = list(reversed(state["history"]))
        page = history[offset : offset + page_size]
        next_offset = offset + len(page)
        return {
            "items": page,
            "returned": len(page),
            "total": len(history),
            "next_cursor": encode_cursor(next_offset) if next_offset < len(history) else None,
            "current_version": state["current_version"],
            "append_only": True,
            "rollback_creates_new_version": True,
            "side_effects": [],
        }

    def patch(
        self,
        payload: ConfigPatchRequest,
        *,
        actor: ConfigActor,
        request_id: str,
    ) -> dict[str, Any]:
        return self._apply_changes(
            changes=payload.changes,
            expected_version=payload.expected_version,
            reason=payload.reason,
            dry_run=payload.dry_run,
            actor=actor,
            request_id=request_id,
            operation="patch",
        )

    def rollback(
        self,
        payload: ConfigRollbackRequest,
        *,
        actor: ConfigActor,
        request_id: str,
    ) -> dict[str, Any]:
        with _CONFIG_WRITE_LOCK:
            state, capture, original = self._load_context()
            self._require_expected_version(
                payload.expected_version,
                state["current_version"],
                dry_run=payload.dry_run,
                actor=actor,
                request_id=request_id,
                action="config.rollback",
                reason=payload.reason,
            )
            target = next(
                (item for item in state["history"] if item["version"] == payload.target_version),
                None,
            )
            if target is None:
                self._record_failure(
                    actor=actor,
                    request_id=request_id,
                    action="config.rollback",
                    reason=payload.reason,
                    current_version=state["current_version"],
                    error_code="ADMIN_CONFIG_ROLLBACK_NOT_AVAILABLE",
                    dry_run=payload.dry_run,
                )
                raise config_error(
                    "ADMIN_CONFIG_ROLLBACK_NOT_AVAILABLE",
                    "The requested config version is not available for rollback.",
                    status_code=409,
                    details={"target_version": payload.target_version},
                )
            proposed = self._validated_snapshot(target["snapshot"])
            return self._preview_or_commit(
                state=state,
                capture=capture,
                original_state=original,
                proposed=proposed,
                expected_version=payload.expected_version,
                reason=payload.reason,
                dry_run=payload.dry_run,
                actor=actor,
                request_id=request_id,
                operation="rollback",
                target_version=payload.target_version,
            )

    def legacy_patch(self, updates: Mapping[str, object], *, request_id: str) -> dict[str, object]:
        try:
            self._validate_legacy_runtime_target()
            validated = validate_feature_flag_updates(updates)
            self._apply_changes(
                changes=validated,
                expected_version=None,
                reason="Legacy PATCH /admin/feature-flags",
                dry_run=False,
                actor=ConfigActor("legacy-feature-flags-admin", "legacy_admin", "legacy_shared_token"),
                request_id=request_id,
                operation="legacy_patch",
            )
            return self.adapter.legacy_status()
        except ConfigRegistryError as exc:
            raise FeatureFlagValidationError(exc.message) from exc

    def legacy_reset(self, *, request_id: str) -> dict[str, object]:
        actor = ConfigActor("legacy-feature-flags-admin", "legacy_admin", "legacy_shared_token")
        reason = "Legacy POST /admin/feature-flags/reset"
        try:
            self._validate_legacy_runtime_target()
            with _CONFIG_WRITE_LOCK:
                state, capture, original = self._load_context()
                proposed = dict(capture.env_defaults)
                diff = build_config_diff(state["current_snapshot"], proposed)
                if not diff and not capture.runtime_override_loaded:
                    return self.adapter.legacy_status()
                if not diff:
                    self._commit_source_only_reset(
                        state=state,
                        capture=capture,
                        original_state=original,
                        actor=actor,
                        request_id=request_id,
                        reason=reason,
                    )
                    return self.adapter.legacy_status()
                self._preview_or_commit(
                    state=state,
                    capture=capture,
                    original_state=original,
                    proposed=proposed,
                    expected_version=state["current_version"],
                    reason=reason,
                    dry_run=False,
                    actor=actor,
                    request_id=request_id,
                    operation="legacy_reset",
                    reset_runtime=True,
                )
                return self.adapter.legacy_status()
        except ConfigRegistryError as exc:
            raise FeatureFlagValidationError(exc.message) from exc

    def _validate_legacy_runtime_target(self) -> None:
        path = feature_flag_runtime_path(self.project_root)
        if path.name in {".env", ".env.example"} or path.suffix.lower() != ".json":
            raise FeatureFlagValidationError("Runtime feature flag paths must not target .env files.")

    def _apply_changes(
        self,
        *,
        changes: Mapping[str, object],
        expected_version: int | None,
        reason: str,
        dry_run: bool,
        actor: ConfigActor,
        request_id: str,
        operation: str,
    ) -> dict[str, Any]:
        unknown = sorted(str(key) for key in changes if str(key) not in CONFIG_REGISTRY)
        if unknown:
            self._record_failure(
                actor=actor,
                request_id=request_id,
                action=f"config.{operation}",
                reason=reason,
                current_version=None,
                error_code="ADMIN_CONFIG_UNKNOWN_KEY",
                dry_run=dry_run,
                keys=unknown,
            )
            raise config_error(
                "ADMIN_CONFIG_UNKNOWN_KEY",
                "One or more config keys are not registered.",
                status_code=404,
                details={"keys": unknown},
            )
        invalid = sorted(str(key) for key, value in changes.items() if type(value) is not bool)
        if invalid:
            raise config_error(
                "ADMIN_CONFIG_VALIDATION_FAILED",
                "Config values must be JSON booleans.",
                status_code=422,
                details={"keys": invalid},
            )
        with _CONFIG_WRITE_LOCK:
            state, capture, original = self._load_context()
            current_version = state["current_version"]
            if expected_version is not None:
                self._require_expected_version(
                    expected_version,
                    current_version,
                    dry_run=dry_run,
                    actor=actor,
                    request_id=request_id,
                    action=f"config.{operation}",
                    reason=reason,
                )
            proposed = dict(state["current_snapshot"])
            proposed.update({str(key): bool(value) for key, value in changes.items()})
            return self._preview_or_commit(
                state=state,
                capture=capture,
                original_state=original,
                proposed=proposed,
                expected_version=current_version if expected_version is None else expected_version,
                reason=reason,
                dry_run=dry_run,
                actor=actor,
                request_id=request_id,
                operation=operation,
            )

    def _preview_or_commit(
        self,
        *,
        state: dict[str, Any],
        capture: FeatureFlagCapture,
        original_state: dict[str, Any] | None,
        proposed: dict[str, bool],
        expected_version: int,
        reason: str,
        dry_run: bool,
        actor: ConfigActor,
        request_id: str,
        operation: str,
        target_version: int | None = None,
        reset_runtime: bool = False,
    ) -> dict[str, Any]:
        proposed = self._validated_snapshot(proposed)
        current = dict(state["current_snapshot"])
        diff = build_config_diff(current, proposed)
        modules = affected_modules(diff)
        base = {
            "operation": operation,
            "dry_run": dry_run,
            "applied": False,
            "no_change": not diff,
            "expected_version": expected_version,
            "previous_version": state["current_version"],
            "new_version": state["current_version"] if not diff else state["current_version"] + 1,
            "target_version": target_version,
            "diff": diff,
            "changed_keys": [item["key"] for item in diff],
            "affected_modules": modules,
            "effective_immediately": True,
            "requires_reload": False,
            "requires_restart": False,
            "warnings": [],
            "current_snapshot": proposed if diff else current,
            "side_effects": [],
        }
        if dry_run:
            self.store.append_audit(
                self._audit_event(
                    actor=actor,
                    request_id=request_id,
                    action=f"config.{operation}",
                    reason=reason,
                    success=True,
                    previous_version=state["current_version"],
                    new_version=state["current_version"],
                    diff=diff,
                    dry_run=True,
                    no_change=not diff,
                    error_code=None,
                )
            )
            return base
        if not diff:
            self.store.append_audit(
                self._audit_event(
                    actor=actor,
                    request_id=request_id,
                    action=f"config.{operation}",
                    reason=reason,
                    success=True,
                    previous_version=state["current_version"],
                    new_version=state["current_version"],
                    diff=[],
                    dry_run=False,
                    no_change=True,
                    error_code=None,
                )
            )
            return base

        new_version = state["current_version"] + 1
        record = self._history_record(
            version=new_version,
            operation=operation,
            reason=reason,
            actor=actor,
            request_id=request_id,
            previous_version=state["current_version"],
            snapshot=proposed,
            diff=diff,
            target_version=target_version,
        )
        next_state = deepcopy(state)
        next_state["current_version"] = new_version
        next_state["current_snapshot"] = dict(proposed)
        next_state["updated_at"] = record["created_at"]
        next_state["history"].append(record)
        warnings, effects = self._commit(
            state=next_state,
            original_state=original_state,
            capture=capture,
            actor=actor,
            request_id=request_id,
            reason=reason,
            operation=operation,
            diff=diff,
            previous_version=record["previous_version"],
            new_version=new_version,
            reset_runtime=reset_runtime,
        )
        base.update(
            {
                "applied": True,
                "new_version": new_version,
                "warnings": warnings,
                "side_effects": effects,
            }
        )
        return base

    def _commit(
        self,
        *,
        state: dict[str, Any],
        original_state: dict[str, Any] | None,
        capture: FeatureFlagCapture,
        actor: ConfigActor,
        request_id: str,
        reason: str,
        operation: str,
        diff: list[dict[str, Any]],
        previous_version: int,
        new_version: int,
        reset_runtime: bool,
    ) -> tuple[list[str], list[str]]:
        proposed = state["current_snapshot"]
        audit_event = self._audit_event(
            actor=actor,
            request_id=request_id,
            action=f"config.{operation}",
            reason=reason,
            success=True,
            previous_version=previous_version,
            new_version=new_version,
            diff=diff,
            dry_run=False,
            no_change=False,
            error_code=None,
        )
        try:
            if reset_runtime:
                self.adapter.reset_to_environment()
            else:
                self.adapter.write_snapshot(proposed)
            self.store.write_state(state)
            self.store.append_audit(audit_event)
        except Exception as exc:
            self._recover_transaction(capture, original_state)
            if isinstance(exc, ConfigRegistryError):
                raise
            if isinstance(exc, FeatureFlagValidationError):
                message = redact_admin_text(str(exc))
            else:
                message = "Config Registry transaction failed."
            raise config_error(
                "ADMIN_CONFIG_APPLY_FAILED",
                message,
                status_code=503,
            ) from exc

        warnings: list[str] = []
        effects = ["runtime_feature_flags", "config_registry_state", "config_history", "config_audit"]
        try:
            self.adapter.append_legacy_audit(
                {
                    "action": "reset" if reset_runtime else "patch",
                    "actor": actor.actor_id,
                    "changed_fields": [item["key"] for item in diff],
                    "previous_flags": capture.effective_flags,
                    "new_flags": proposed,
                    "request_id": request_id,
                    "config_version": new_version,
                }
            )
            effects.append("legacy_feature_flag_audit")
        except Exception:
            warnings.append("LEGACY_FEATURE_FLAG_AUDIT_UNAVAILABLE")
        return warnings, effects

    def _commit_source_only_reset(
        self,
        *,
        state: dict[str, Any],
        capture: FeatureFlagCapture,
        original_state: dict[str, Any] | None,
        actor: ConfigActor,
        request_id: str,
        reason: str,
    ) -> None:
        audit = self._audit_event(
            actor=actor,
            request_id=request_id,
            action="config.legacy_reset",
            reason=reason,
            success=True,
            previous_version=state["current_version"],
            new_version=state["current_version"],
            diff=[],
            dry_run=False,
            no_change=True,
            error_code=None,
        )
        try:
            self.adapter.reset_to_environment()
            self.store.append_audit(audit)
        except Exception:
            self._recover_transaction(capture, original_state)
            raise
        try:
            self.adapter.append_legacy_audit(
                {
                    "action": "reset",
                    "actor": actor.actor_id,
                    "changed_fields": [],
                    "previous_flags": capture.effective_flags,
                    "new_flags": capture.env_defaults,
                    "request_id": request_id,
                    "config_version": state["current_version"],
                }
            )
        except Exception:
            pass

    def _recover_transaction(
        self,
        capture: FeatureFlagCapture,
        original_state: dict[str, Any] | None,
    ) -> None:
        try:
            self.adapter.restore(capture)
            self.store.restore_state(original_state)
        except Exception as exc:
            raise config_error(
                "ADMIN_CONFIG_ROLLBACK_FAILED",
                "Config Registry transaction recovery failed.",
                status_code=503,
            ) from exc

    def _load_context(self) -> tuple[dict[str, Any], FeatureFlagCapture, dict[str, Any] | None]:
        capture = self.adapter.capture()
        if not capture.runtime_override_valid:
            raise config_error(
                "ADMIN_CONFIG_SOURCE_INVALID",
                "The controlled runtime feature flag source is invalid.",
                status_code=409,
                details={"errors": list(capture.runtime_override_errors)},
            )
        original = self.store.load_state()
        if original is None:
            state = self._baseline_state(capture)
        else:
            self._validate_state(original)
            state = deepcopy(original)
        if state["current_snapshot"] != capture.effective_flags:
            diff = build_config_diff(state["current_snapshot"], capture.effective_flags)
            version = state["current_version"] + 1
            record = self._history_record(
                version=version,
                operation="source_reconcile",
                reason="Observed a controlled feature-flag source change.",
                actor=ConfigActor("system", "system", "source_reconcile"),
                request_id=None,
                previous_version=state["current_version"],
                snapshot=capture.effective_flags,
                diff=diff,
                target_version=None,
            )
            state["current_version"] = version
            state["current_snapshot"] = dict(capture.effective_flags)
            state["updated_at"] = record["created_at"]
            state["history"].append(record)
        return state, capture, deepcopy(original) if original is not None else None

    def _baseline_state(self, capture: FeatureFlagCapture) -> dict[str, Any]:
        created_at = capture.updated_at or _utc_now()
        snapshot = self._validated_snapshot(capture.effective_flags)
        record = {
            "version": 1,
            "operation": "baseline",
            "reason": "Initial baseline from effective runtime feature flags.",
            "actor_id": "system",
            "actor_role": "system",
            "auth_source": "system_initialization",
            "request_id": None,
            "created_at": created_at,
            "previous_version": None,
            "target_version": None,
            "changed_keys": [],
            "diff": [],
            "snapshot": snapshot,
            "success": True,
        }
        return {
            "format_version": 1,
            "registry": "runtime_feature_flags",
            "current_version": 1,
            "current_snapshot": snapshot,
            "updated_at": created_at,
            "history": [record],
        }

    def _validate_state(self, state: Mapping[str, Any]) -> None:
        try:
            version = int(state["current_version"])
            snapshot = self._validated_snapshot(state["current_snapshot"])
            history = state["history"]
            valid = (
                state.get("format_version") == 1
                and state.get("registry") == "runtime_feature_flags"
                and version >= 1
                and isinstance(history, list)
                and bool(history)
                and int(history[-1]["version"]) == version
                and self._validated_snapshot(history[-1]["snapshot"]) == snapshot
                and [int(item["version"]) for item in history] == list(range(1, version + 1))
            )
        except (KeyError, TypeError, ValueError, ConfigRegistryError):
            valid = False
        if not valid:
            raise config_error(
                "ADMIN_CONFIG_HISTORY_INVALID",
                "Config Registry history is unavailable or invalid.",
                status_code=503,
            )

    def _validated_snapshot(self, value: Mapping[str, object]) -> dict[str, bool]:
        if not isinstance(value, Mapping) or set(value) != set(CONFIG_KEYS):
            raise config_error(
                "ADMIN_CONFIG_VALIDATION_FAILED",
                "Config snapshots must contain exactly the registered keys.",
                status_code=422,
            )
        if any(type(item) is not bool for item in value.values()):
            raise config_error(
                "ADMIN_CONFIG_VALIDATION_FAILED",
                "Config snapshot values must be JSON booleans.",
                status_code=422,
            )
        return {key: bool(value[key]) for key in CONFIG_KEYS}

    def _items(self, state: dict[str, Any], capture: FeatureFlagCapture) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for key in CONFIG_KEYS:
            item = CONFIG_REGISTRY[key].schema()
            item.update(
                {
                    "value": state["current_snapshot"][key],
                    "effective_value": state["current_snapshot"][key],
                    "default": capture.env_defaults[key],
                    "source": "runtime" if key in capture.runtime_override else "environment",
                    "version": state["current_version"],
                }
            )
            result.append(item)
        return result

    def _history_record(
        self,
        *,
        version: int,
        operation: str,
        reason: str,
        actor: ConfigActor,
        request_id: str | None,
        previous_version: int | None,
        snapshot: Mapping[str, bool],
        diff: list[dict[str, Any]],
        target_version: int | None,
    ) -> dict[str, Any]:
        return {
            "version": version,
            "operation": operation,
            "reason": redact_admin_text(reason),
            "actor_id": actor.actor_id,
            "actor_role": actor.role,
            "auth_source": actor.auth_source,
            "request_id": request_id,
            "created_at": _utc_now(),
            "previous_version": previous_version,
            "target_version": target_version,
            "changed_keys": [item["key"] for item in diff],
            "diff": diff,
            "snapshot": self._validated_snapshot(snapshot),
            "success": True,
        }

    def _audit_event(
        self,
        *,
        actor: ConfigActor,
        request_id: str,
        action: str,
        reason: str,
        success: bool,
        previous_version: int | None,
        new_version: int | None,
        diff: list[dict[str, Any]],
        dry_run: bool,
        no_change: bool,
        error_code: str | None,
    ) -> dict[str, Any]:
        return {
            "event_id": f"config-audit-{uuid4().hex}",
            "at": _utc_now(),
            "source": "config_registry",
            "auth_source": actor.auth_source,
            "actor_id": actor.actor_id,
            "actor_role": actor.role,
            "action": action,
            "request_id": request_id,
            "success": success,
            "reason": redact_admin_text(reason),
            "keys": [item["key"] for item in diff],
            "previous_version": previous_version,
            "new_version": new_version,
            "dry_run": dry_run,
            "no_change": no_change,
            "error_code": error_code,
            "diff": diff,
            "side_effects": [] if (not success or dry_run or no_change) else ["runtime_feature_flags", "config_history"],
            "sensitive_fields_redacted": True,
        }

    def _record_failure(
        self,
        *,
        actor: ConfigActor,
        request_id: str,
        action: str,
        reason: str,
        current_version: int | None,
        error_code: str,
        dry_run: bool,
        keys: list[str] | None = None,
    ) -> None:
        diff = [
            {"key": key, "changed": False, "affected_modules": []}
            for key in (keys or [])
        ]
        self.store.append_audit(
            self._audit_event(
                actor=actor,
                request_id=request_id,
                action=action,
                reason=reason,
                success=False,
                previous_version=current_version,
                new_version=current_version,
                diff=diff,
                dry_run=dry_run,
                no_change=True,
                error_code=error_code,
            )
        )

    def _require_expected_version(
        self,
        expected: int,
        current: int,
        *,
        dry_run: bool,
        actor: ConfigActor,
        request_id: str,
        action: str,
        reason: str,
    ) -> None:
        if expected == current:
            return
        self._record_failure(
            actor=actor,
            request_id=request_id,
            action=action,
            reason=reason,
            current_version=current,
            error_code="ADMIN_CONFIG_VERSION_CONFLICT",
            dry_run=dry_run,
        )
        raise config_error(
            "ADMIN_CONFIG_VERSION_CONFLICT",
            "Config has changed since it was read.",
            status_code=412,
            details={"expected_version": expected, "current_version": current},
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_true(name: str) -> bool:
    import os

    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_SERVICE = ConfigRegistryService(PROJECT_ROOT)


def get_config_registry_service() -> ConfigRegistryService:
    return _DEFAULT_CONFIG_SERVICE


__all__ = ["ConfigActor", "ConfigRegistryService", "get_config_registry_service"]
