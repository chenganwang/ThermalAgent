from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any
from uuid import uuid4

from services.admin_service.auth import AdminIdentity
from services.admin_service.contracts import AdminAPIError

from .audit import ActionAuditStore
from .context import ActionExecutionContext
from .execution import ActionExecutor
from .registry import ActionDescriptor, ActionRegistry
from .schemas import ActionRequest
from .security import sanitize_action_value, validate_action_parameters


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ActionService:
    def __init__(
        self,
        *,
        registry: ActionRegistry | None = None,
        executor: ActionExecutor | None = None,
        audit: ActionAuditStore | None = None,
    ) -> None:
        self.registry = registry or ActionRegistry()
        self.executor = executor or ActionExecutor()
        self.audit = audit or ActionAuditStore(PROJECT_ROOT)

    def list_actions(
        self,
        identity: AdminIdentity,
        *,
        category: str | None = None,
        risk_level: str | None = None,
        enabled: bool | None = None,
        available: bool | None = None,
    ) -> dict[str, Any]:
        _require_permission(identity, "action.read")
        items = [self.registry.public_descriptor(item) for item in self.registry.descriptors()]
        if category is not None:
            items = [item for item in items if item["category"] == category]
        if risk_level is not None:
            items = [item for item in items if item["risk_level"] == risk_level]
        if enabled is not None:
            items = [item for item in items if item["enabled"] is enabled]
        if available is not None:
            items = [item for item in items if item["available"] is available]
        return {
            "items": items,
            "returned": len(items),
            "read_only_actions_only": True,
            "execution_mode": "synchronous",
            "job_manager_enabled": False,
        }

    def get_action(self, identity: AdminIdentity, action_id: str) -> dict[str, Any]:
        _require_permission(identity, "action.read")
        return self.registry.public_descriptor(self.registry.require(action_id))

    def dry_run(
        self,
        identity: AdminIdentity,
        action_id: str,
        payload: ActionRequest,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        invocation_id = _invocation_id()
        started_at = _utc_now()
        started = perf_counter()
        descriptor: ActionDescriptor | None = None
        normalized: dict[str, Any] = {}
        try:
            descriptor = self.registry.require(action_id)
            _require_permission(identity, "action.dry_run")
            prepared = self._prepare(descriptor, payload.parameters)
            normalized = prepared["normalized_parameters"]
            allowed = bool(prepared["allowed"])
            status = "succeeded" if allowed else "blocked"
            result = {
                "invocation_id": invocation_id,
                "action_id": descriptor.action_id,
                "allowed": allowed,
                "risk_level": descriptor.risk_level,
                "read_only": descriptor.read_only,
                "side_effects": list(descriptor.side_effects),
                "normalized_parameters": normalized,
                "preconditions": prepared["preconditions"],
                "warnings": prepared["warnings"],
                "timeout_seconds": descriptor.timeout_seconds,
                "execution_mode": descriptor.execution_mode,
                "handler_invoked": False,
            }
            self._record(
                descriptor=descriptor,
                identity=identity,
                invocation_id=invocation_id,
                request_id=request_id,
                started_at=started_at,
                duration_ms=_duration_ms(started),
                dry_run=True,
                success=allowed,
                status=status,
                parameters=normalized,
                result_summary={"allowed": allowed, "warning_count": len(prepared["warnings"])},
                error_code=None if allowed else "ADMIN_ACTION_CONCURRENCY_LIMIT",
            )
            return result
        except AdminAPIError as exc:
            if exc.code != "ADMIN_ACTION_AUDIT_FAILED":
                self._record_error(
                    descriptor=descriptor,
                    identity=identity,
                    invocation_id=invocation_id,
                    action_id=action_id,
                    request_id=request_id,
                    started_at=started_at,
                    duration_ms=_duration_ms(started),
                    dry_run=True,
                    parameters=normalized,
                    error=exc,
                )
            raise

    def invoke(
        self,
        identity: AdminIdentity,
        action_id: str,
        payload: ActionRequest,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        invocation_id = _invocation_id()
        started_at = _utc_now()
        started = perf_counter()
        descriptor: ActionDescriptor | None = None
        normalized: dict[str, Any] = {}
        try:
            descriptor = self.registry.require(action_id)
            _require_permission(identity, descriptor.required_permission)
            prepared = self._prepare(descriptor, payload.parameters)
            normalized = prepared["normalized_parameters"]
            if not prepared["allowed"]:
                raise AdminAPIError(
                    "ADMIN_ACTION_CONCURRENCY_LIMIT",
                    "Action concurrency limit is currently reached.",
                    status_code=429,
                    retryable=True,
                )
            context = ActionExecutionContext(
                invocation_id=invocation_id,
                action_id=descriptor.action_id,
                request_id=request_id,
                actor_id=identity.actor_id,
                deadline_monotonic=monotonic() + descriptor.timeout_seconds,
            )
            handler_result = self.executor.execute(descriptor, context, normalized)
            safe_result = sanitize_action_value(handler_result)
            finished_at = _utc_now()
            duration_ms = _duration_ms(started)
            status = "succeeded" if bool(handler_result.success) else "failed"
            result_summary = {
                "success": bool(handler_result.success),
                "summary": safe_result.get("summary", {}),
                "metrics": safe_result.get("metrics", {}),
                "details": safe_result.get("details", {}),
            }
            result = {
                "invocation_id": invocation_id,
                "action_id": descriptor.action_id,
                "status": status,
                "dry_run": False,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "result_summary": result_summary,
                "warnings": safe_result.get("warnings", []),
                "side_effects": list(descriptor.side_effects),
            }
            self._record(
                descriptor=descriptor,
                identity=identity,
                invocation_id=invocation_id,
                request_id=request_id,
                started_at=started_at,
                duration_ms=duration_ms,
                dry_run=False,
                success=bool(handler_result.success),
                status=status,
                parameters=normalized,
                result_summary=result_summary,
                error_code=None if handler_result.success else "ADMIN_ACTION_EXECUTION_FAILED",
            )
            return result
        except AdminAPIError as exc:
            if exc.code != "ADMIN_ACTION_AUDIT_FAILED":
                self._record_error(
                    descriptor=descriptor,
                    identity=identity,
                    invocation_id=invocation_id,
                    action_id=action_id,
                    request_id=request_id,
                    started_at=started_at,
                    duration_ms=_duration_ms(started),
                    dry_run=False,
                    parameters=normalized,
                    error=exc,
                )
            raise

    def _prepare(self, descriptor: ActionDescriptor, parameters: dict[str, Any]) -> dict[str, Any]:
        if not descriptor.enabled:
            raise AdminAPIError(
                "ADMIN_ACTION_DISABLED",
                "Action is disabled.",
                status_code=409,
            )
        available, availability_reason = self.registry.availability(descriptor)
        if not available:
            raise AdminAPIError(
                "ADMIN_ACTION_UNAVAILABLE",
                availability_reason or "Action is unavailable.",
                status_code=503,
                retryable=True,
            )
        if not descriptor.supports_dry_run:
            raise AdminAPIError(
                "ADMIN_ACTION_DRY_RUN_NOT_SUPPORTED",
                "Action does not support dry-run.",
                status_code=409,
            )
        normalized = validate_action_parameters(descriptor.parameter_model, parameters)
        if descriptor.risk_level != "low" or not descriptor.read_only or descriptor.side_effects:
            raise AdminAPIError(
                "ADMIN_ACTION_PERMISSION_DENIED",
                "Action risk policy does not permit execution in Phase C-1.",
                status_code=403,
            )
        try:
            preconditions = descriptor.precondition_checker(normalized)
        except Exception as exc:
            raise AdminAPIError(
                "ADMIN_ACTION_UNAVAILABLE",
                "Action precondition check failed safely.",
                status_code=503,
                retryable=True,
            ) from exc
        if not bool(preconditions.get("passed")):
            raise AdminAPIError(
                "ADMIN_ACTION_UNAVAILABLE",
                "Action preconditions are not satisfied.",
                status_code=503,
                details={"checks": sanitize_action_value(preconditions.get("checks") or [])},
                retryable=True,
            )
        concurrency_available = self.executor.guard.available(
            descriptor.action_id,
            descriptor.concurrency_limit,
        )
        warnings = list(preconditions.get("warnings") or [])
        if not concurrency_available:
            warnings.append("Action concurrency limit is currently reached.")
        return {
            "allowed": concurrency_available,
            "normalized_parameters": normalized,
            "preconditions": sanitize_action_value(preconditions.get("checks") or []),
            "warnings": sanitize_action_value(warnings),
        }

    def _record_error(
        self,
        *,
        descriptor: ActionDescriptor | None,
        identity: AdminIdentity,
        invocation_id: str,
        action_id: str,
        request_id: str,
        started_at: str,
        duration_ms: int,
        dry_run: bool,
        parameters: dict[str, Any],
        error: AdminAPIError,
    ) -> None:
        status = "timed_out" if error.code == "ADMIN_ACTION_TIMEOUT" else "blocked"
        if error.code == "ADMIN_ACTION_EXECUTION_FAILED":
            status = "failed"
        if descriptor is not None:
            self._record(
                descriptor=descriptor,
                identity=identity,
                invocation_id=invocation_id,
                request_id=request_id,
                started_at=started_at,
                duration_ms=duration_ms,
                dry_run=dry_run,
                success=False,
                status=status,
                parameters=parameters,
                result_summary={},
                error_code=error.code,
            )
            return
        self.audit.record(
            invocation_id=invocation_id,
            action_id=str(action_id or "unknown")[:128],
            actor_id=identity.actor_id,
            actor_type=identity.role,
            permission="action.dry_run" if dry_run else "action.execute.low",
            risk_level="low",
            dry_run=dry_run,
            success=False,
            status=status,
            request_id=request_id,
            started_at=started_at,
            duration_ms=duration_ms,
            parameters={},
            result_summary={},
            error_code=error.code,
        )

    def _record(
        self,
        *,
        descriptor: ActionDescriptor,
        identity: AdminIdentity,
        invocation_id: str,
        request_id: str,
        started_at: str,
        duration_ms: int,
        dry_run: bool,
        success: bool,
        status: str,
        parameters: dict[str, Any],
        result_summary: dict[str, Any],
        error_code: str | None,
    ) -> None:
        permission = "action.dry_run" if dry_run else descriptor.required_permission
        self.audit.record(
            invocation_id=invocation_id,
            action_id=descriptor.action_id,
            actor_id=identity.actor_id,
            actor_type=identity.role,
            permission=permission,
            risk_level=descriptor.risk_level,
            dry_run=dry_run,
            success=success,
            status=status,
            request_id=request_id,
            started_at=started_at,
            duration_ms=duration_ms,
            parameters=parameters,
            result_summary=result_summary,
            error_code=error_code,
        )


def _require_permission(identity: AdminIdentity, permission: str) -> None:
    if permission not in identity.permissions:
        raise AdminAPIError(
            "ADMIN_ACTION_PERMISSION_DENIED",
            "Admin identity does not have the required Action permission.",
            status_code=403,
            details={"required_permission": permission},
        )


def _invocation_id() -> str:
    return f"act-{uuid4().hex}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


_DEFAULT_ACTION_SERVICE = ActionService()


def get_action_service() -> ActionService:
    return _DEFAULT_ACTION_SERVICE


__all__ = ["ActionService", "PROJECT_ROOT", "get_action_service"]
