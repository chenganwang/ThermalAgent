from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from pydantic import BaseModel

from services.admin_service.contracts import AdminAPIError

from .context import ActionExecutionContext
from .handlers import (
    executor_registry_preconditions,
    matlab_environment_check,
    matlab_environment_preconditions,
    model_registry_preconditions,
    scenario_catalog_preconditions,
    validate_executor_registry,
    validate_model_registry,
    validate_scenario_catalog,
)
from .schemas import ActionHandlerResult, EmptyActionParameters


ActionHandler = Callable[[ActionExecutionContext, dict[str, Any]], ActionHandlerResult]
PreconditionChecker = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ActionDescriptor:
    action_id: str
    name: str
    description: str
    category: str
    risk_level: str
    read_only: bool
    side_effects: tuple[str, ...]
    supports_dry_run: bool
    execution_mode: str
    required_permission: str
    timeout_seconds: float
    concurrency_limit: int
    enabled: bool
    parameter_model: type[BaseModel]
    result_schema_version: str
    handler: ActionHandler
    precondition_checker: PreconditionChecker

    def public_dict(self, *, available: bool, availability_reason: str | None) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "read_only": self.read_only,
            "side_effects": list(self.side_effects),
            "supports_dry_run": self.supports_dry_run,
            "execution_mode": self.execution_mode,
            "required_permission": self.required_permission,
            "timeout_seconds": self.timeout_seconds,
            "concurrency_limit": self.concurrency_limit,
            "enabled": self.enabled,
            "available": available,
            "availability_reason": availability_reason,
            "parameter_schema": self.parameter_model.model_json_schema(),
            "result_schema_version": self.result_schema_version,
        }


def build_action_descriptors() -> tuple[ActionDescriptor, ...]:
    return (
        ActionDescriptor(
            action_id="simulation.catalog.validate",
            name="校验 Scenario Catalog",
            description="只读加载固定 Scenario Catalog，并校验 ID、Schema 与模型引用。",
            category="simulation",
            risk_level="low",
            read_only=True,
            side_effects=(),
            supports_dry_run=True,
            execution_mode="synchronous",
            required_permission="action.execute.low",
            timeout_seconds=5,
            concurrency_limit=2,
            enabled=True,
            parameter_model=EmptyActionParameters,
            result_schema_version="1.0",
            handler=validate_scenario_catalog,
            precondition_checker=scenario_catalog_preconditions,
        ),
        ActionDescriptor(
            action_id="simulation.model_registry.validate",
            name="校验 Model Registry",
            description="只读校验模型 ID、场景/求解器引用、状态和 operator model 执行边界。",
            category="simulation",
            risk_level="low",
            read_only=True,
            side_effects=(),
            supports_dry_run=True,
            execution_mode="synchronous",
            required_permission="action.execute.low",
            timeout_seconds=5,
            concurrency_limit=2,
            enabled=True,
            parameter_model=EmptyActionParameters,
            result_schema_version="1.0",
            handler=validate_model_registry,
            precondition_checker=model_registry_preconditions,
        ),
        ActionDescriptor(
            action_id="simulation.executor_registry.validate",
            name="校验 Executor Registry",
            description="只读校验固定 Executor ID、solver 映射和 handler 注册关系，不运行 executor。",
            category="simulation",
            risk_level="low",
            read_only=True,
            side_effects=(),
            supports_dry_run=True,
            execution_mode="synchronous",
            required_permission="action.execute.low",
            timeout_seconds=5,
            concurrency_limit=2,
            enabled=True,
            parameter_model=EmptyActionParameters,
            result_schema_version="1.0",
            handler=validate_executor_registry,
            precondition_checker=executor_registry_preconditions,
        ),
        ActionDescriptor(
            action_id="simulation.matlab.environment_check",
            name="检查 MATLAB 环境",
            description="只做固定 discovery/import/guard 摘要检查；强制 start_engine=false。",
            category="simulation",
            risk_level="low",
            read_only=True,
            side_effects=(),
            supports_dry_run=True,
            execution_mode="synchronous",
            required_permission="action.execute.low",
            timeout_seconds=8,
            concurrency_limit=1,
            enabled=True,
            parameter_model=EmptyActionParameters,
            result_schema_version="1.0",
            handler=matlab_environment_check,
            precondition_checker=matlab_environment_preconditions,
        ),
    )


class ActionRegistry:
    def __init__(self, descriptors: Iterable[ActionDescriptor] | None = None) -> None:
        items = tuple(descriptors or build_action_descriptors())
        by_id = {item.action_id: item for item in items}
        if len(items) != len(by_id):
            raise ValueError("Duplicate Admin action_id")
        for item in items:
            _validate_descriptor(item)
        self._ordered = items
        self._by_id = by_id

    def descriptors(self) -> tuple[ActionDescriptor, ...]:
        return self._ordered

    def require(self, action_id: str) -> ActionDescriptor:
        descriptor = self._by_id.get(str(action_id or ""))
        if descriptor is None:
            raise AdminAPIError(
                "ADMIN_ACTION_NOT_FOUND",
                "Action is not registered.",
                status_code=404,
                details={"action_id": str(action_id or "")[:128]},
            )
        return descriptor

    @staticmethod
    def availability(descriptor: ActionDescriptor) -> tuple[bool, str | None]:
        if not descriptor.enabled:
            return False, "Action is disabled by the static registry."
        try:
            result = descriptor.precondition_checker({})
        except Exception:
            return False, "Action precondition inventory could not be checked."
        if bool(result.get("passed")):
            return True, None
        warnings = result.get("warnings") or []
        return False, str(warnings[0]) if warnings else "Action preconditions are not satisfied."

    def public_descriptor(self, descriptor: ActionDescriptor) -> dict[str, Any]:
        available, reason = self.availability(descriptor)
        return descriptor.public_dict(available=available, availability_reason=reason)


def _validate_descriptor(descriptor: ActionDescriptor) -> None:
    if descriptor.risk_level != "low":
        raise ValueError("Phase C-1 only permits low-risk actions")
    if not descriptor.read_only or descriptor.side_effects:
        raise ValueError("Phase C-1 actions must be read-only with no business side effects")
    if descriptor.execution_mode != "synchronous":
        raise ValueError("Phase C-1 only permits synchronous actions")
    if descriptor.required_permission != "action.execute.low":
        raise ValueError("Phase C-1 action permission must remain action.execute.low")
    if not descriptor.supports_dry_run:
        raise ValueError("Phase C-1 actions must support dry-run")
    if descriptor.timeout_seconds <= 0 or descriptor.timeout_seconds > 30:
        raise ValueError("Phase C-1 action timeout must be bounded to 30 seconds")
    if descriptor.concurrency_limit <= 0 or descriptor.concurrency_limit > 8:
        raise ValueError("Phase C-1 action concurrency must be bounded")
    if not callable(descriptor.handler) or not callable(descriptor.precondition_checker):
        raise ValueError("Phase C-1 handlers and preconditions must be fixed callables")


__all__ = [
    "ActionDescriptor",
    "ActionHandler",
    "ActionRegistry",
    "PreconditionChecker",
    "build_action_descriptors",
]
