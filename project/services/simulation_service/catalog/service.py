from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Mapping
from uuid import uuid4

from ..capabilities import build_simulation_capability
from .executor_registry import ExecutorRegistry
from .model_registry import ModelRegistry
from .provenance import build_evidence_summary, sanitize_public_payload
from .scenario_catalog import ScenarioCatalog
from .validation import validate_scenario_params


class SimulationCatalogService:
    def __init__(
        self,
        *,
        scenarios: ScenarioCatalog | None = None,
        models: ModelRegistry | None = None,
        executors: ExecutorRegistry | None = None,
        capability_provider: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self.scenarios = scenarios or ScenarioCatalog()
        self.models = models or ModelRegistry()
        self.executors = executors or ExecutorRegistry()
        self.capability_provider = capability_provider or build_simulation_capability
        scenario_ids = {x.scenario_id for x in self.scenarios.list()}
        self.models.validate_scenarios(scenario_ids)
        for scenario in self.scenarios.list():
            if scenario.default_model_id and scenario.default_model_id not in scenario.supported_models:
                raise RuntimeError(f"default model is not supported: {scenario.scenario_id}")
            input_names = {str(x["name"]) for x in scenario.input_schema}
            output_names = {str(x["name"]) for x in scenario.output_schema}
            for model_id in scenario.supported_models:
                model = self.models.get(model_id)
                if model is None or model.scenario_id != scenario.scenario_id:
                    raise RuntimeError(f"scenario references invalid model: {scenario.scenario_id}/{model_id}")
                if set(model.allowed_inputs) != input_names or set(model.outputs) != output_names:
                    raise RuntimeError(f"model schema differs from scenario: {model_id}")

    def catalog(self) -> dict[str, Any]:
        scenarios = self.list_scenarios()
        models = self.list_models()
        executors = [x.to_dict() for x in self.executors.list()]
        capability = dict(self.capability_provider())
        matlab_provider = (capability.get("providers") or {}).get("matlab") or {}
        return sanitize_public_payload({
            "catalog_version": self.scenarios.catalog_version,
            "registry_version": self.models.registry_version,
            "domains": sorted({x["domain"] for x in scenarios}),
            "solvers": [
                {"solver": "python", "status": "available", "execution_mode": "controlled_function"},
                {
                    "solver": "matlab",
                    "status": "available" if matlab_provider.get("safe_to_run_demo") else "unavailable",
                    "execution_mode": "controlled_function",
                },
                {"solver": "simulink", "status": "planned", "execution_mode": "registered_model_only"},
                {"solver": "openmodelica", "status": "planned", "execution_mode": "registered_model_only"},
                {"solver": "openfoam", "status": "preparation_only", "execution_mode": "registered_model_only"},
                {"solver": "comsol", "status": "preparation_only", "execution_mode": "registered_model_only"},
                {"solver": "ansys_fluent", "status": "preparation_only", "execution_mode": "registered_model_only"},
            ],
            "scenarios": scenarios,
            "models": models,
            "executors": executors,
        })

    def list_scenarios(self, *, domain: str | None = None, solver: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        items = self.scenarios.list(domain=domain, status=status)
        if solver is not None:
            allowed = {x.scenario_id for x in self.models.list(solver=solver)}
            items = [x for x in items if x.scenario_id in allowed]
        return [x.to_dict() for x in items]

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        item = self.scenarios.get(scenario_id)
        return item.to_dict() if item else None

    def list_models(self, *, scenario_id: str | None = None, solver: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return [sanitize_public_payload(x.to_public_dict()) for x in self.models.list(scenario_id=scenario_id, solver=solver, status=status)]

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        item = self.models.get(model_id)
        return sanitize_public_payload(item.to_public_dict()) if item else None

    def plan(self, scenario_id: str, params: Mapping[str, Any] | None, *, model_id: str | None = None) -> dict[str, Any]:
        scenario = self.scenarios.get(scenario_id)
        if scenario is None:
            return _failed_plan(scenario_id, model_id, "unknown_scenario", "Scenario is not registered.")
        selected_id = model_id or scenario.default_model_id
        model = self.models.get(selected_id or "")
        if model is None:
            return _failed_plan(scenario_id, selected_id, "unknown_model", "Model is not registered.")
        is_operator_model = model.registration_type == "operator_registered"
        if (model.model_id not in scenario.supported_models and not is_operator_model) or model.scenario_id != scenario.scenario_id:
            return _failed_plan(scenario_id, selected_id, "unsupported_model", "Model does not belong to this scenario.")
        validation = validate_scenario_params(scenario, params)
        executor = self.executors.for_model(model)
        capability = dict(self.capability_provider())
        feature_enabled = bool(capability.get("feature_enabled"))
        solver_guard_passed = _solver_guard_passed(model.solver, capability)
        trusted_registration = model.registration_type in {"built_in", "operator_registered"}
        executable_status = scenario.status == "available" and model.status == "available" and trusted_registration and executor is not None and executor.status == "available"
        ready = bool(validation.valid and executable_status)
        execution_allowed = bool(feature_enabled and solver_guard_passed and ready)
        warnings: list[str] = []
        if not model.human_validated:
            warnings.append("model_not_human_validated")
        if scenario.status != "available" or model.execution_mode == "preparation_only":
            warnings.append("preparation_only_or_experimental")
        if not feature_enabled:
            warnings.append("simulation_feature_disabled")
        if not solver_guard_passed:
            warnings.append(f"{model.solver}_guard_not_passed")
        if is_operator_model and model.status in {"unvalidated", "preparation_only"}:
            warnings.append("model_unvalidated")
            return sanitize_public_payload({
                "ready": False,
                "status": "model_unvalidated",
                "message": "模型已登记，但尚未通过执行验证。",
                "scenario_id": scenario.scenario_id,
                "model_id": model.model_id,
                "solver": model.solver,
                "normalized_params": validation.normalized_params,
                "missing_parameters": validation.missing_parameters,
                "errors": validation.errors,
                "warnings": warnings,
                "execution_allowed": False,
                "feature_enabled": feature_enabled,
                "solver_guard_passed": solver_guard_passed,
                "executor_status": "unavailable",
                "execution_mode": model.execution_mode,
            })
        return sanitize_public_payload({
            "ready": ready,
            "status": "ready" if ready else ("invalid" if not validation.valid else "blocked"),
            "scenario_id": scenario.scenario_id,
            "model_id": model.model_id,
            "solver": model.solver,
            "normalized_params": validation.normalized_params,
            "missing_parameters": validation.missing_parameters,
            "errors": validation.errors,
            "warnings": warnings,
            "execution_allowed": execution_allowed,
            "feature_enabled": feature_enabled,
            "solver_guard_passed": solver_guard_passed,
            "executor_status": executor.status if executor else "unavailable",
            "execution_mode": model.execution_mode,
        })

    def run(self, scenario_id: str, params: Mapping[str, Any] | None, *, model_id: str | None = None) -> dict[str, Any]:
        plan = self.plan(scenario_id, params, model_id=model_id)
        if not plan.get("ready") or not plan.get("execution_allowed"):
            model_unvalidated = plan.get("status") == "model_unvalidated"
            return {"success": False, "status": "blocked" if model_unvalidated else "rejected", "plan": plan, "error": {"code": "model_unvalidated" if model_unvalidated else "simulation_plan_not_ready", "message": "模型已登记，但尚未通过执行验证。" if model_unvalidated else "Simulation run requires a ready execution plan."}}
        scenario = self.scenarios.get(str(plan["scenario_id"]))
        model = self.models.get(str(plan["model_id"]))
        assert scenario is not None and model is not None
        executor = self.executors.for_model(model)
        assert executor is not None
        started = perf_counter()
        try:
            raw = self.executors.run(model, dict(plan["normalized_params"]))
        except Exception as exc:
            return sanitize_public_payload({"success": False, "status": "failed", "plan": plan, "error": {"code": "controlled_executor_failed", "message": type(exc).__name__}})
        duration_ms = int(raw.get("duration_ms") if raw.get("duration_ms") is not None else (perf_counter() - started) * 1000)
        outputs = dict(raw.get("outputs") or {})
        warnings = list(raw.get("warnings") or [])
        evidence = build_evidence_summary(
            scenario,
            model,
            executor,
            raw,
            inputs=dict(plan["normalized_params"]),
            duration_ms=duration_ms,
        )
        response = {
            "success": bool(raw.get("success")), "status": str(raw.get("status") or "failed"),
            "run_id": f"sim-{uuid4().hex}", "scenario_id": scenario.scenario_id,
            "scenario": {"scenario_id": scenario.scenario_id, "name_zh": scenario.name_zh},
            "model": {"model_id": model.model_id, "name_zh": model.name_zh, "version": model.version, "human_validated": model.human_validated},
            "solver": model.solver, "outputs": outputs, "units": dict(raw.get("units") or {}),
            "formula": raw.get("formula"), "assumptions": list(raw.get("assumptions") or model.assumptions),
            "warnings": warnings, "duration_ms": duration_ms, "evidence_id": evidence["evidence_id"],
            "evidence": evidence,
        }
        if raw.get("matlab_version"):
            response["engine_version"] = raw["matlab_version"]
        if model.solver == "matlab":
            response["is_real_solver"] = bool(raw.get("is_real_matlab"))
        if raw.get("error"):
            response["error"] = raw["error"]
        return sanitize_public_payload(response)


def _solver_guard_passed(solver: str, capability: Mapping[str, Any]) -> bool:
    if solver == "matlab":
        provider = (capability.get("providers") or {}).get("matlab") or {}
        return bool(capability.get("enabled") and capability.get("backend_guard_passed") and provider.get("safe_to_run_demo", capability.get("enabled")))
    if solver == "python":
        return True
    return False


def _failed_plan(scenario_id: str, model_id: str | None, code: str, message: str) -> dict[str, Any]:
    return {"ready": False, "status": "invalid", "scenario_id": scenario_id, "model_id": model_id, "solver": None, "normalized_params": {}, "missing_parameters": [], "errors": [{"field": "model_id" if "model" in code else "scenario_id", "code": code, "message": message}], "warnings": [], "execution_allowed": False}


_DEFAULT_SERVICE: SimulationCatalogService | None = None


def get_catalog_service() -> SimulationCatalogService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = SimulationCatalogService()
    return _DEFAULT_SERVICE


def reset_catalog_service() -> None:
    """Drop the cached catalog so a newly registered runtime model is visible."""

    global _DEFAULT_SERVICE
    _DEFAULT_SERVICE = None


def get_catalog() -> dict[str, Any]:
    return get_catalog_service().catalog()


def plan_simulation(scenario_id: str, params: Mapping[str, Any] | None, *, model_id: str | None = None) -> dict[str, Any]:
    return get_catalog_service().plan(scenario_id, params, model_id=model_id)


def run_simulation(scenario_id: str, params: Mapping[str, Any] | None, *, model_id: str | None = None) -> dict[str, Any]:
    return get_catalog_service().run(scenario_id, params, model_id=model_id)


__all__ = ["SimulationCatalogService", "get_catalog", "get_catalog_service", "plan_simulation", "reset_catalog_service", "run_simulation"]
