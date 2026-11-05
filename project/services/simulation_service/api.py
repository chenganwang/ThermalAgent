from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from .capabilities import build_simulation_capability
from .catalog import SimulationCatalogService, get_catalog_service, reset_catalog_service
from .catalog.provenance import sanitize_public_payload
from .contracts import SimulationRunRequest
from .matlab.adapter import MatlabSimulationAdapter
from .matlab.runtime import get_matlab_runtime_manager
from .model_assets import (
    ApprovalRequest,
    ModelAssetError,
    ModelAssetLifecycleService,
    RegistrationRequest,
)
from .service import SimulationService


class SimulationRunPayload(BaseModel):
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    user_query: str | None = None
    adapter_name: str | None = None
    mode: str = "mock"
    timeout_seconds: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    requested_backend: str | None = None
    allow_mock: bool = True
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_request(self) -> SimulationRunRequest:
        return SimulationRunRequest(
            tool_name=self.tool_name,
            inputs=dict(self.inputs or {}),
            session_id=self.session_id,
            user_query=self.user_query,
            adapter_name=self.adapter_name,
            mode=self.mode,
            timeout_seconds=self.timeout_seconds,
            options=dict(self.options or {}),
            parameters=dict(self.parameters or {}),
            units=dict(self.units or {}),
            config=dict(self.config or {}),
            requested_backend=self.requested_backend,
            allow_mock=self.allow_mock,
            trace_id=self.trace_id,
            metadata=dict(self.metadata or {}),
        )


class MatlabDemoPayload(BaseModel):
    demo_name: str
    params: dict[str, Any] = Field(default_factory=dict)


class ScenarioSimulationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    model_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class ModelAssetApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    proposed_model_id: str
    operator_notes: str = ""


class ModelAssetRejectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class ModelAssetBlockPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "operator_blocked"


class ModelAssetRegisterPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solver: str
    adapter_id: str | None
    allowed_inputs: list[str]
    operator_confirmation: bool
    version: str = "0.1.0"
    status: str = "unvalidated"


_DEFAULT_SERVICE = SimulationService.default()


def get_simulation_service() -> SimulationService:
    return _DEFAULT_SERVICE


def get_matlab_simulation_adapter() -> MatlabSimulationAdapter:
    return MatlabSimulationAdapter()


get_simulation_catalog_service = get_catalog_service

_DEFAULT_MODEL_ASSET_SERVICE: ModelAssetLifecycleService | None = None


def get_model_asset_service() -> ModelAssetLifecycleService:
    global _DEFAULT_MODEL_ASSET_SERVICE
    if _DEFAULT_MODEL_ASSET_SERVICE is None:
        _DEFAULT_MODEL_ASSET_SERVICE = ModelAssetLifecycleService()
    return _DEFAULT_MODEL_ASSET_SERVICE


def require_model_asset_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> None:
    if not asset_service.config.admin_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "model_asset_admin_disabled"})
    supplied = (x_admin_token or "").strip()
    expected = os.getenv("ADMIN_FEATURE_FLAGS_TOKEN", "").strip()
    if not supplied:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "missing_admin_token"})
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "invalid_admin_token"})


def _raise_model_asset_error(exc: ModelAssetError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from exc


def _public_matlab_demo_payload(result: Any) -> dict[str, Any]:
    """Build the public demo response without exposing host-local evidence paths."""

    payload = dict(result.to_dict())
    payload.pop("evidence_path", None)
    payload.pop("license_confirmed_by_operator", None)
    if payload.get("success") is True and payload.get("demo_name") == "heat_conduction_1d":
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        outputs = dict(payload.get("outputs") or {})
        units = dict(payload.get("units") or {})
        try:
            outputs["temperature_difference_k"] = float(inputs["t_hot_c"]) - float(inputs["t_cold_c"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            units["temperature_difference_k"] = "K"
        payload["outputs"] = outputs
        payload["units"] = units
    return sanitize_public_payload(payload)


router = APIRouter(prefix="/simulation", tags=["simulation"])
model_asset_admin_router = APIRouter(
    prefix="/admin/simulation/model-assets",
    tags=["simulation-model-assets-admin"],
    dependencies=[Depends(require_model_asset_admin)],
)


@router.get("/status")
def simulation_status(service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    status = dict(service.describe_status())
    status.update(build_simulation_capability())
    return status


@router.get("/adapters/status")
def simulation_adapter_status(service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    return {"adapters": service.list_adapter_statuses()}


@router.get("/history/backend/status")
def simulation_history_backend_status(service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    return service.history_backend.health_check()


@router.get("/migration/status")
def simulation_migration_status(service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    backend = service.history_backend
    if hasattr(backend, "migration_status"):
        return {"history_backend": backend.health_check(), "migration": backend.migration_status()}
    return {
        "history_backend": backend.health_check(),
        "migration": {"ready": False, "reason": "migration_status_not_applicable"},
    }


@router.get("/matlab/status")
def simulation_matlab_status() -> dict[str, Any]:
    legacy = MatlabSimulationAdapter().status().to_dict()
    connection = get_matlab_runtime_manager().connection_status(start=False).to_dict()
    legacy.update(connection)
    legacy["installed"] = bool(connection.get("matlab_root_detected"))
    legacy["last_error"] = connection.get("engine_error")
    return sanitize_public_payload(legacy)


@router.get("/catalog")
def simulation_catalog(
    catalog_service: SimulationCatalogService = Depends(get_simulation_catalog_service),
) -> dict[str, Any]:
    return catalog_service.catalog()


@router.get("/scenarios")
def simulation_scenarios(
    domain: str | None = None,
    solver: str | None = None,
    status: str | None = None,
    catalog_service: SimulationCatalogService = Depends(get_simulation_catalog_service),
) -> dict[str, Any]:
    return {
        "scenarios": catalog_service.list_scenarios(
            domain=domain,
            solver=solver,
            status=status,
        )
    }


@router.get("/scenarios/{scenario_id}")
def simulation_scenario(
    scenario_id: str,
    catalog_service: SimulationCatalogService = Depends(get_simulation_catalog_service),
) -> dict[str, Any]:
    scenario = catalog_service.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail={"code": "simulation_scenario_not_found"})
    return scenario


@router.post("/plan")
def simulation_plan(
    payload: ScenarioSimulationPayload,
    catalog_service: SimulationCatalogService = Depends(get_simulation_catalog_service),
) -> dict[str, Any]:
    return catalog_service.plan(payload.scenario_id, payload.params, model_id=payload.model_id)


@router.post("/matlab/demo")
def simulation_matlab_demo(
    payload: MatlabDemoPayload,
    adapter: MatlabSimulationAdapter = Depends(get_matlab_simulation_adapter),
) -> dict[str, Any]:
    result = adapter.run_demo(
        payload.demo_name,
        payload.params,
        require_api_enabled=True,
    )
    public_result = _public_matlab_demo_payload(result)
    if not result.success:
        status_code = 403 if result.status in {"disabled", "not_configured", "license_not_confirmed", "engine_not_installed"} else 400
        raise HTTPException(status_code=status_code, detail=public_result)
    return public_result


@router.get("/tools")
def simulation_tools(service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    return {"tools": service.list_tools()}


@router.get("/tools/{tool_name}")
def simulation_tool(tool_name: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    tool = service.get_tool(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail="Simulation tool not found.")
    return tool


@router.post("/tasks")
def create_simulation_task(
    payload: SimulationRunPayload,
    service: SimulationService = Depends(get_simulation_service),
) -> dict[str, Any]:
    return service.create_task(payload.to_request())


@router.get("/tasks/{task_id}")
def get_simulation_task(task_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Simulation task not found.")
    return task


@router.post("/tasks/{task_id}/run")
def run_simulation_task(task_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    try:
        return service.replay_task(task_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Simulation task not found.") from exc


@router.post("/run")
def run_simulation(
    payload: SimulationRunPayload | ScenarioSimulationPayload,
    service: SimulationService = Depends(get_simulation_service),
    catalog_service: SimulationCatalogService = Depends(get_simulation_catalog_service),
) -> dict[str, Any]:
    if isinstance(payload, ScenarioSimulationPayload):
        return catalog_service.run(payload.scenario_id, payload.params, model_id=payload.model_id)
    return service.run(payload.to_request()).to_dict()


@router.get("/jobs/{job_id}")
def get_simulation_job(job_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Simulation job not found.")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_simulation_job(job_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    return service.cancel_job(job_id)


@router.get("/history")
def simulation_history(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    tool_name: str | None = None,
    adapter_name: str | None = None,
    trace_id: str | None = None,
    is_mock: bool | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    service: SimulationService = Depends(get_simulation_service),
) -> dict[str, Any]:
    max_limit = int(getattr(service.config, "history_query_limit_max", 200) or 200)
    if limit < 0 or limit > max_limit or offset < 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_simulation_history_limit",
                "message": f"limit must be between 0 and {max_limit}; offset must be non-negative.",
                "limit": limit,
                "offset": offset,
                "max_limit": max_limit,
            },
        )
    try:
        records = service.list_history_records(
            limit=limit,
            offset=offset,
            status=status,
            tool_name=tool_name,
            adapter_name=adapter_name,
            trace_id=trace_id,
            is_mock=is_mock,
            created_after=created_after,
            created_before=created_before,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "simulation_history_backend_unavailable", "message": str(exc)},
        ) from exc
    return {
        "records": records,
        "limit": limit,
        "offset": offset,
    }


@router.get("/history/{task_id}")
def simulation_task_history(task_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    record = service.get_history_record(task_id)
    if record is not None:
        return {"record": record}
    events = service.list_history(task_id)
    if events:
        return {"task_id": task_id, "events": events}
    raise HTTPException(status_code=404, detail={"code": "simulation_run_not_found", "run_id": task_id})


@router.get("/results/{run_id}")
def simulation_result(run_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    result = service.get_result(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "simulation_run_not_found", "run_id": run_id})
    return {"result": result}


@router.post("/replay/{run_id}")
def replay_simulation_run(run_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    try:
        return service.replay_run(run_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "simulation_run_not_found", "run_id": run_id}) from exc


@router.post("/tasks/{task_id}/replay")
def replay_simulation_task(task_id: str, service: SimulationService = Depends(get_simulation_service)) -> dict[str, Any]:
    try:
        return service.replay_task(task_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Simulation task not found.") from exc


@router.get("/models")
def simulation_models(
    scenario_id: str | None = None,
    solver: str | None = None,
    status: str | None = None,
    catalog_service: SimulationCatalogService = Depends(get_simulation_catalog_service),
) -> dict[str, Any]:
    models = catalog_service.list_models(
        scenario_id=scenario_id,
        solver=solver,
        status=status,
    )
    catalog = catalog_service.catalog()
    matlab_status = next(
        (item.get("status") for item in catalog.get("solvers") or () if item.get("solver") == "matlab"),
        "unavailable",
    )
    matlab_available = matlab_status == "available"
    return {
        "models": models,
        "count": len(models),
        "matlab_available": matlab_available,
        "catalog_version": catalog.get("catalog_version"),
        "warnings": [] if matlab_available else ["matlab_unavailable"],
    }


@router.get("/models/{model_id}")
def simulation_model(
    model_id: str,
    catalog_service: SimulationCatalogService = Depends(get_simulation_catalog_service),
) -> dict[str, Any]:
    model = catalog_service.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail={"code": "simulation_model_not_found"})
    return model


@router.get("/model-assets")
def simulation_model_assets(
    status: str | None = None,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        return {**asset_service.capabilities(), "assets": asset_service.list_public(status=status)}
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@router.post("/model-assets/upload", status_code=status.HTTP_201_CREATED)
async def upload_simulation_model_asset(
    request: Request,
    file: UploadFile = File(...),
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        form = await request.form()
        unexpected = sorted(str(key) for key in form.keys() if key != "file")
        if unexpected or len(form.getlist("file")) != 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "model_asset_upload_field_forbidden", "fields": unexpected},
            )
        return asset_service.get_public(
            asset_service.upload(
                filename=file.filename or "",
                source=file.file,
                mime_type=file.content_type,
                uploaded_by="user",
            ).asset_id
        )
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@router.get("/model-assets/{asset_id}")
def simulation_model_asset(
    asset_id: str,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        return asset_service.get_public(asset_id)
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@router.post("/model-assets/{asset_id}/submit-review")
def submit_simulation_model_asset_review(
    asset_id: str,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        return asset_service.get_public(asset_service.submit_review(asset_id).asset_id)
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@model_asset_admin_router.get("")
def admin_simulation_model_assets(
    status: str | None = None,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        return {"assets": asset_service.list_admin(status=status)}
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@model_asset_admin_router.get("/{asset_id}")
def admin_simulation_model_asset(
    asset_id: str,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        return asset_service.get_admin(asset_id)
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@model_asset_admin_router.post("/{asset_id}/approve")
def approve_simulation_model_asset(
    asset_id: str,
    payload: ModelAssetApprovalPayload,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        asset = asset_service.approve(
            asset_id,
            ApprovalRequest(
                scenario_id=payload.scenario_id,
                proposed_model_id=payload.proposed_model_id,
                operator_notes=payload.operator_notes,
            ),
        )
        return asset_service.get_admin(asset.asset_id)
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@model_asset_admin_router.post("/{asset_id}/reject")
def reject_simulation_model_asset(
    asset_id: str,
    payload: ModelAssetRejectPayload,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        asset = asset_service.reject(asset_id, payload.reason)
        return asset_service.get_admin(asset.asset_id)
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@model_asset_admin_router.post("/{asset_id}/block")
def block_simulation_model_asset(
    asset_id: str,
    payload: ModelAssetBlockPayload | None = None,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        asset = asset_service.block(asset_id, payload.reason if payload else "operator_blocked")
        return asset_service.get_admin(asset.asset_id)
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


@model_asset_admin_router.post("/{asset_id}/register")
def register_simulation_model_asset(
    asset_id: str,
    payload: ModelAssetRegisterPayload,
    asset_service: ModelAssetLifecycleService = Depends(get_model_asset_service),
) -> dict[str, Any]:
    try:
        model = asset_service.register(
            asset_id,
            RegistrationRequest(
                solver=payload.solver,
                adapter_id=payload.adapter_id,
                allowed_inputs=tuple(payload.allowed_inputs),
                operator_confirmation=payload.operator_confirmation,
                version=payload.version,
                status=payload.status,
            ),
        )
        reset_catalog_service()
        return sanitize_public_payload({"success": True, "model": model, "asset": asset_service.get_admin(asset_id)})
    except ModelAssetError as exc:
        _raise_model_asset_error(exc)


__all__ = [
    "MatlabDemoPayload",
    "ScenarioSimulationPayload",
    "SimulationRunPayload",
    "get_matlab_simulation_adapter",
    "get_model_asset_service",
    "get_simulation_catalog_service",
    "get_simulation_service",
    "model_asset_admin_router",
    "require_model_asset_admin",
    "router",
]
