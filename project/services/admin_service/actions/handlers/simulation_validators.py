from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.simulation_service.catalog.executor_registry import ExecutorRegistry
from services.simulation_service.catalog.model_registry import ModelRegistry
from services.simulation_service.catalog.scenario_catalog import ScenarioCatalog

from ..context import ActionExecutionContext
from ..schemas import ActionHandlerResult


_CATALOG_DATA_DIR = Path(__file__).resolve().parents[3] / "simulation_service" / "catalog" / "data"
_SCENARIOS_FILE = _CATALOG_DATA_DIR / "scenarios.json"
_MODELS_FILE = _CATALOG_DATA_DIR / "models.json"
_EXECUTORS_FILE = _CATALOG_DATA_DIR / "executors.json"


def scenario_catalog_preconditions(_parameters: dict[str, Any]) -> dict[str, Any]:
    return _resource_preconditions((_SCENARIOS_FILE, _MODELS_FILE), "scenario_catalog_resources")


def model_registry_preconditions(_parameters: dict[str, Any]) -> dict[str, Any]:
    return _resource_preconditions((_SCENARIOS_FILE, _MODELS_FILE, _EXECUTORS_FILE), "model_registry_resources")


def executor_registry_preconditions(_parameters: dict[str, Any]) -> dict[str, Any]:
    return _resource_preconditions((_MODELS_FILE, _EXECUTORS_FILE), "executor_registry_resources")


def validate_scenario_catalog(
    context: ActionExecutionContext,
    _parameters: dict[str, Any],
) -> ActionHandlerResult:
    try:
        scenarios = ScenarioCatalog()
        models = ModelRegistry()
        errors: list[dict[str, Any]] = []
        for scenario in scenarios.list():
            context.deadline_exceeded()
            if scenario.default_model_id and scenario.default_model_id not in scenario.supported_models:
                errors.append(_issue("DEFAULT_MODEL_NOT_SUPPORTED", scenario.scenario_id, "Default model is not in supported_models."))
            for model_id in scenario.supported_models:
                model = models.get(model_id)
                if model is None or model.scenario_id != scenario.scenario_id:
                    errors.append(_issue("INVALID_MODEL_REFERENCE", scenario.scenario_id, "Scenario references an unknown or mismatched model."))
        return _validation_result("scenario_catalog", len(scenarios.list()), errors)
    except Exception:
        return _load_failed("SCENARIO_CATALOG_LOAD_FAILED", "Scenario Catalog could not be loaded and validated.")


def validate_model_registry(
    context: ActionExecutionContext,
    _parameters: dict[str, Any],
) -> ActionHandlerResult:
    try:
        scenarios = ScenarioCatalog()
        models = ModelRegistry()
        executors = ExecutorRegistry()
        scenario_ids = {item.scenario_id for item in scenarios.list()}
        errors: list[dict[str, Any]] = []
        for model in models.list():
            context.deadline_exceeded()
            if model.scenario_id not in scenario_ids:
                errors.append(_issue("UNKNOWN_SCENARIO_REFERENCE", model.model_id, "Model references an unknown scenario."))
            if model.status == "available":
                executor = executors.for_model(model)
                if executor is None or executor.status != "available" or executor.solver != model.solver:
                    errors.append(_issue("INVALID_EXECUTOR_REFERENCE", model.model_id, "Available model has no matching available executor."))
            if model.registration_type == "operator_registered" and model.status == "available":
                file_record = model.file or {}
                if not model.hash or not file_record.get("operator_registered"):
                    errors.append(_issue("OPERATOR_MODEL_NOT_VERIFIED", model.model_id, "Operator model cannot claim availability without verification."))
        warnings = [
            "Unvalidated and preparation-only models remain non-executable by policy."
        ]
        return _validation_result("model_registry", len(models.list()), errors, warnings=warnings)
    except Exception:
        return _load_failed("MODEL_REGISTRY_LOAD_FAILED", "Model Registry could not be loaded and validated.")


def validate_executor_registry(
    context: ActionExecutionContext,
    _parameters: dict[str, Any],
) -> ActionHandlerResult:
    try:
        raw = json.loads(_EXECUTORS_FILE.read_text(encoding="utf-8"))
        records = list(raw.get("executors") or ())
        identifiers = [str(item.get("executor_id") or "") for item in records]
        registry = ExecutorRegistry()
        models = ModelRegistry()
        errors: list[dict[str, Any]] = []
        if not all(identifiers) or len(identifiers) != len(set(identifiers)):
            errors.append(_issue("DUPLICATE_OR_EMPTY_EXECUTOR_ID", None, "Executor IDs must be present and unique."))
        for definition in registry.list():
            context.deadline_exceeded()
            expected = f"{definition.adapter_id}:{definition.entrypoint_id}"
            if definition.executor_id != expected:
                errors.append(_issue("EXECUTOR_ID_MISMATCH", definition.executor_id, "Executor ID does not match its fixed adapter and entrypoint."))
        for model in models.list(status="available"):
            definition = registry.for_model(model)
            if definition is None or definition.status != "available" or definition.solver != model.solver:
                errors.append(_issue("AVAILABLE_MODEL_EXECUTOR_MISMATCH", model.model_id, "Available model is not mapped to a matching executor."))
        return _validation_result("executor_registry", len(registry.list()), errors)
    except Exception:
        return _load_failed("EXECUTOR_REGISTRY_LOAD_FAILED", "Executor Registry could not be loaded and validated.")


def _resource_preconditions(paths: tuple[Path, ...], check_id: str) -> dict[str, Any]:
    present = all(path.is_file() for path in paths)
    return {
        "passed": present,
        "checks": [{"check_id": check_id, "passed": present}],
        "warnings": [] if present else ["One or more bundled registry resources are unavailable."],
    }


def _issue(code: str, resource_id: str | None, message: str) -> dict[str, Any]:
    return {"code": code, "resource_id": resource_id, "message": message}


def _validation_result(
    resource: str,
    item_count: int,
    errors: list[dict[str, Any]],
    *,
    warnings: list[str] | None = None,
) -> ActionHandlerResult:
    valid = not errors
    return ActionHandlerResult(
        success=True,
        summary={"resource": resource, "valid": valid, "item_count": item_count},
        metrics={"item_count": item_count, "error_count": len(errors), "write_count": 0, "executor_run_count": 0},
        warnings=list(warnings or []),
        details={"errors": errors},
    )


def _load_failed(code: str, message: str) -> ActionHandlerResult:
    return ActionHandlerResult(
        success=True,
        summary={"valid": False, "item_count": 0},
        metrics={"item_count": 0, "error_count": 1, "write_count": 0, "executor_run_count": 0},
        details={"errors": [_issue(code, None, message)]},
    )


__all__ = [
    "executor_registry_preconditions",
    "model_registry_preconditions",
    "scenario_catalog_preconditions",
    "validate_executor_registry",
    "validate_model_registry",
    "validate_scenario_catalog",
]
