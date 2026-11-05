from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from ..agent_orchestrator import ThermalAgent
from ..analysis.report_exporter import export_markdown_report, resolve_exported_report_path
from ..config import AppConfig, load_config
from ..db import DB
from ..rag_chain import build_context_view, retrieve_only, retrieve_only_with_plan
from ..retriever import warmup_retrieval_runtime
from ...simulation_service.api import model_asset_admin_router, router as simulation_router
from ...simulation_service.fluent.api import cfd_router, router as fluent_router
from ...physics_service.api import router as physics_router
from ...engineering_service.api import router as engineering_router
from ...pem_service.api import router as pem_router
from ...pem_service.extensions import domain_catalog, extension_catalog
from ...engineering_service.execution import configured_store
from ...simulation_service.capabilities import build_simulation_capability
from ...simulation_service.feature_flags import (
    DEFAULT_FEATURE_FLAGS,
    FeatureFlagValidationError,
    admin_feature_flags_enabled,
    feature_flags_status,
    get_effective_feature_flags,
)
from ...simulation_service.matlab.runtime import get_matlab_runtime_manager
from ...admin_service import install_admin_api
from ...admin_service.config import get_config_registry_service
from ...admin_service.v1.runtime import get_generated_model_janitor, get_generated_model_operation_recorder
from ..simulation.simulation_executor import ConfirmedSimulationExecutor
from ..simulation.simulation_orchestrator import SimulationModeOrchestrator
from .readiness import build_readiness_payload, new_readiness_state, record_readiness_check
from .cors import allowed_origins
from .schemas import (
    AgentAnalyzeExportRequest,
    AgentAnalyzeRequest,
    AgentAnalyzeResponse,
    AgentAnswerRequest,
    AgentAnswerResponse,
    AgentMemoryResetRequest,
    HealthResponse,
    OpenWebUIToolSpecResponse,
    RetrieveContextResponse,
    RetrieveHit,
    RetrieveRequest,
    RetrieveResponse,
)

APP_TITLE = "ThermalAgent API"
APP_VERSION = "0.1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


def _build_agent(cfg: AppConfig) -> ThermalAgent:
    executor = ConfirmedSimulationExecutor(
        operation_recorder=get_generated_model_operation_recorder(),
    )
    return ThermalAgent(
        cfg=cfg,
        simulation_orchestrator=SimulationModeOrchestrator(executor=executor),
        engineering_store=configured_store(cfg.paths.project_root),
    )


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


def _load_runtime_cfg() -> AppConfig:
    root = os.getenv("RAG_PROJECT_ROOT", "").strip()
    return load_config(project_root=Path(root) if root else None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    readiness_state = new_readiness_state()
    app.state.readiness = readiness_state
    record_readiness_check(readiness_state, "api", "ready", safe_message="API application initialized.")
    generated_model_janitor = None
    try:
        generated_model_janitor = get_generated_model_janitor()
        await asyncio.to_thread(generated_model_janitor.start)
    except Exception as exc:
        logger.error("Generated-model janitor startup failed: error_type=%s", type(exc).__name__)
    try:
        cfg = _load_runtime_cfg()
    except Exception as exc:
        logger.error("Configuration load failed during API startup: error_type=%s", type(exc).__name__)
        app.state.cfg = None
        app.state.db = None
        app.state.db_error = type(exc).__name__
        app.state.agent = None
        record_readiness_check(
            readiness_state,
            "configuration",
            "not_ready",
            error_code="CONFIGURATION_LOAD_FAILED",
            error_type=type(exc).__name__,
            safe_message="Configuration could not be loaded.",
        )
        for component in ("database", "retrieval", "index"):
            record_readiness_check(
                readiness_state,
                component,
                "not_ready",
                error_code="CONFIGURATION_REQUIRED",
                safe_message="Check is blocked until configuration is available.",
            )
        record_readiness_check(readiness_state, "matlab", "disabled", safe_message="Optional MATLAB check was not started.")
        record_readiness_check(readiness_state, "simulation", "disabled", safe_message="Optional simulation check was not started.")
        try:
            yield
        finally:
            if generated_model_janitor is not None:
                await asyncio.to_thread(generated_model_janitor.stop)
        return
    app.state.cfg = cfg
    record_readiness_check(readiness_state, "configuration", "ready", safe_message="Configuration loaded.")
    app.state.db = None
    app.state.db_error = None
    try:
        app.state.db = DB.create(cfg)
        record_readiness_check(readiness_state, "database", "ready", safe_message="Database connection initialized.")
    except Exception as exc:
        app.state.db_error = type(exc).__name__
        logger.error("Database initialization failed during API startup: error_type=%s", type(exc).__name__)
        record_readiness_check(
            readiness_state,
            "database",
            "not_ready",
            error_code="DATABASE_INITIALIZATION_FAILED",
            error_type=type(exc).__name__,
            safe_message="Database initialization failed.",
        )
    required_index_paths = [cfg.paths.faiss_index_path]
    if cfg.bm25.enabled:
        required_index_paths.append(cfg.paths.bm25_corpus_path)
    if all(path.is_file() for path in required_index_paths):
        record_readiness_check(readiness_state, "index", "ready", safe_message="Configured index files are present.")
    else:
        record_readiness_check(
            readiness_state,
            "index",
            "not_ready",
            error_code="INDEX_FILES_MISSING",
            safe_message="One or more configured index files are unavailable.",
        )
    if cfg.retrieval.warmup_on_startup:
        try:
            warmup_result = warmup_retrieval_runtime(cfg)
            warmup_status = str(warmup_result.get("status") or "ready") if isinstance(warmup_result, dict) else "ready"
            if warmup_status == "not_ready":
                record_readiness_check(
                    readiness_state,
                    "retrieval",
                    "not_ready",
                    error_code=str(warmup_result.get("error_code") or "RETRIEVAL_WARMUP_REQUIRED_FAILURE"),
                    error_type=str(warmup_result.get("error_type") or "WarmupFailure"),
                    safe_message="Retrieval warmup completed with required failures.",
                )
            elif warmup_status == "degraded":
                record_readiness_check(
                    readiness_state,
                    "retrieval",
                    "degraded",
                    error_code="RETRIEVAL_WARMUP_DEGRADED",
                    safe_message="Retrieval warmup completed with optional failures.",
                )
            else:
                record_readiness_check(readiness_state, "retrieval", "ready", safe_message="Retrieval warmup completed.")
        except Exception as exc:
            logger.error("Retrieval warmup failed during API startup: error_type=%s", type(exc).__name__)
            record_readiness_check(
                readiness_state,
                "retrieval",
                "not_ready",
                error_code="RETRIEVAL_WARMUP_FAILED",
                error_type=type(exc).__name__,
                safe_message="Retrieval warmup failed.",
            )
    elif app.state.db is None or not all(path.is_file() for path in required_index_paths):
        record_readiness_check(
            readiness_state,
            "retrieval",
            "not_ready",
            error_code="RETRIEVAL_RESOURCES_UNAVAILABLE",
            safe_message="Required retrieval resources are unavailable.",
        )
    else:
        record_readiness_check(readiness_state, "retrieval", "ready", safe_message="Retrieval resources passed startup checks.")
    app.state.agent = _build_agent(cfg)
    record_readiness_check(readiness_state, "simulation", "ready", safe_message="Simulation API is available.")
    matlab_runtime = None
    try:
        matlab_runtime = get_matlab_runtime_manager()
    except Exception as exc:
        logger.error("MATLAB runtime lookup failed during API startup: error_type=%s", type(exc).__name__)
        record_readiness_check(
            readiness_state,
            "matlab",
            "unavailable",
            error_code="MATLAB_RUNTIME_UNAVAILABLE",
            error_type=type(exc).__name__,
            safe_message="Optional MATLAB runtime is unavailable.",
        )
    if matlab_runtime is not None and (
        matlab_runtime.config.enabled
        and matlab_runtime.config.allow_engine_start
        and matlab_runtime.config.allow_api
    ):
        try:
            await asyncio.to_thread(matlab_runtime.warmup)
            record_readiness_check(readiness_state, "matlab", "ready", safe_message="MATLAB warmup completed.")
        except Exception as exc:
            logger.error("MATLAB warmup failed during API startup: error_type=%s", type(exc).__name__)
            record_readiness_check(
                readiness_state,
                "matlab",
                "unavailable",
                error_code="MATLAB_WARMUP_FAILED",
                error_type=type(exc).__name__,
                safe_message="Optional MATLAB runtime is unavailable.",
            )
    elif matlab_runtime is not None:
        record_readiness_check(readiness_state, "matlab", "disabled", safe_message="Optional MATLAB warmup is disabled.")
    try:
        yield
    finally:
        if generated_model_janitor is not None:
            await asyncio.to_thread(generated_model_janitor.stop)
        if matlab_runtime is not None:
            try:
                await asyncio.to_thread(matlab_runtime.shutdown)
            except Exception as exc:
                logger.error("MATLAB shutdown failed: error_type=%s", type(exc).__name__)


def _require_api_key(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("RAG_API_KEY", "").strip()
    if not expected:
        return
    token = (authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
        )


def _require_admin_feature_flags(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    if not admin_feature_flags_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Feature flags admin API is disabled.")
    expected = os.getenv("ADMIN_FEATURE_FLAGS_TOKEN", "").strip()
    supplied = (x_admin_token or "").strip()
    if not supplied:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing admin token.")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token.")


def get_cfg(request: Request) -> AppConfig:
    cfg = getattr(request.app.state, "cfg", None)
    if cfg is None:
        cfg = _load_runtime_cfg()
        request.app.state.cfg = cfg
    return cfg


def get_agent(request: Request) -> ThermalAgent:
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        agent = _build_agent(get_cfg(request))
        request.app.state.agent = agent
    return agent


def _normalize_export_formats(payload: AgentAnalyzeExportRequest) -> list[str]:
    formats = payload.export_formats or ([payload.export_format] if payload.export_format else ["md"])
    normalized = [str(item).lower().strip() for item in formats if str(item).strip()]
    return normalized or ["md"]


def _ensure_report_output_requested(requested_outputs: list[str]) -> list[str]:
    outputs: list[str] = []
    seen: set[str] = set()
    for item in requested_outputs:
        normalized = str(item).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key not in seen:
            outputs.append(normalized)
            seen.add(key)
    if "report" not in seen and "markdown_report" not in seen:
        outputs.append("report")
    return outputs


def _public_export_payload(export_result: dict[str, object]) -> dict[str, object]:
    return {
        "format": export_result.get("format"),
        "report_id": export_result.get("report_id"),
        "filename": export_result.get("filename"),
        "relative_path": export_result.get("relative_path"),
        "download_url": export_result.get("download_url"),
        "warnings": export_result.get("warnings") or [],
    }


def _extract_report_metadata(metadata: dict) -> dict:
    report = metadata.get("report")
    if isinstance(report, dict):
        return report
    analysis = metadata.get("analysis")
    if isinstance(analysis, dict) and isinstance(analysis.get("report"), dict):
        return analysis["report"]
    return {}


def _attach_report_export(metadata: dict, report: dict, export_payload: dict[str, object]) -> dict:
    updated = dict(metadata or {})

    report_with_export = dict(report)
    report_with_export["exports"] = [export_payload]
    updated["report"] = report_with_export

    analysis = dict(updated.get("analysis") or {})
    analysis_report = {key: value for key, value in report_with_export.items() if key != "content"}
    analysis_report["exports"] = [export_payload]
    analysis["report"] = analysis_report
    updated["analysis"] = analysis
    return updated


def _report_module_inventory() -> dict[str, object]:
    report_builder = PROJECT_ROOT / "services" / "retrieval_service" / "analysis" / "report_builder.py"
    report_exporter = PROJECT_ROOT / "services" / "retrieval_service" / "analysis" / "report_exporter.py"
    has_report_builder = report_builder.exists()
    has_report_exporter = report_exporter.exists()
    if has_report_builder and has_report_exporter:
        module_status = "experimental"
        message = "Report generation is available through the Agent analysis export workflow."
    elif has_report_builder or has_report_exporter:
        module_status = "design_only"
        message = "Report generation pieces exist, but the backend workflow is incomplete."
    else:
        module_status = "not_found"
        message = "Report generation backend module was not found."
    return {
        "module_status": module_status,
        "has_report_builder": has_report_builder,
        "has_report_exporter": has_report_exporter,
        "message": message,
    }


def build_report_capability(feature_flags: dict[str, bool] | None = None) -> dict[str, object]:
    inventory = _report_module_inventory()
    flags = dict(get_effective_feature_flags() if feature_flags is None else feature_flags)
    show_in_frontend = bool(flags.get("report_visible", DEFAULT_FEATURE_FLAGS["report_visible"]))
    requested_enabled = bool(flags.get("report_enabled", DEFAULT_FEATURE_FLAGS["report_enabled"]))
    module_status = str(inventory["module_status"])
    backend_available = module_status in {"experimental", "available"}
    enabled = bool(requested_enabled and backend_available)
    if not show_in_frontend:
        message = "Report UI is hidden by frontend feature flag."
    elif not requested_enabled:
        message = "Report UI can be shown, but generation is disabled by frontend feature flag."
    else:
        message = str(inventory["message"])
    return {
        "show_in_frontend": show_in_frontend,
        "enabled": enabled,
        "feature_enabled": requested_enabled,
        "api_enabled": enabled,
        "backend_available": backend_available,
        "requires_operator_enable": True,
        "status": module_status,
        "module_status": module_status,
        "generation_endpoint": "/agent/analyze/export" if backend_available else None,
        "status_endpoint": "/report/status",
        "supported_formats": ["md"] if backend_available else [],
        "standalone_generate_endpoint": None,
        "agent_export_required": backend_available,
        "message": message,
    }


def build_capabilities_payload() -> dict[str, object]:
    feature_flags = get_effective_feature_flags()
    return {
        "backend": {
            "status": "ok",
            "app": APP_TITLE,
            "version": APP_VERSION,
            "docs_url": "/docs",
            "health_endpoint": "/health",
        },
        "retrieval": {
            "enabled": True,
            "sources_enabled": True,
            "retrieval_count_contract": True,
            "endpoints": {
                "retrieve": "/retrieve",
                "retrieve_context": "/retrieve_context",
                "tool_spec": "/openwebui/tool-spec",
            },
        },
        "agent": {
            "enabled": True,
            "endpoint": "/agent/answer",
            "analysis_endpoint": "/agent/analyze",
            "report_export_endpoint": "/agent/analyze/export",
        },
        "simulation": build_simulation_capability(feature_flags),
        "engineering": {
            "persistence_enabled": os.getenv("ENGINEERING_PERSISTENCE_ENABLED", "true").lower() not in {"false", "0", "off"},
            "history_endpoint": "/engineering/runs", "projects_endpoint": "/engineering/projects",
            "reference_solver_endpoint": "/engineering/reference/solve",
            "recovery_mode": "explicit_linked_deterministic_reexecution",
            "reference_model": "steady-1d-constant-k-v1", "real_cfd_verified": False,
        },
        "report_generation": build_report_capability(feature_flags),
        "domains": domain_catalog(),
        "pem_flowfield": {"enabled": True, "status": "mvp", "endpoint": "/pem/catalog",
                          "observed_results_only": True, "real_fluent_execution_verified": False,
                          "extensions": extension_catalog()["extensions"]},
    }


app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)


async def safe_request_validation(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": [
        {"type": item["type"], "loc": list(item["loc"]), "msg": item["msg"]}
        for item in exc.errors()
    ]})


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(simulation_router, dependencies=[Depends(_require_api_key)])
app.include_router(model_asset_admin_router, dependencies=[Depends(_require_api_key)])
app.include_router(fluent_router, dependencies=[Depends(_require_api_key)])
app.include_router(cfd_router, dependencies=[Depends(_require_api_key)])
app.include_router(physics_router, dependencies=[Depends(_require_api_key)])
app.include_router(engineering_router, dependencies=[Depends(_require_api_key)])
app.include_router(pem_router, dependencies=[Depends(_require_api_key)])
install_admin_api(app)
_admin_validation_handler = app.exception_handlers[RequestValidationError]


@app.exception_handler(RequestValidationError)
async def validated_api_request(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/agent/") or request.url.path.startswith("/engineering/"):
        return await safe_request_validation(request, exc)
    return await _admin_validation_handler(request, exc)


@app.get("/health", response_model=HealthResponse, dependencies=[Depends(_require_api_key)])
def health() -> HealthResponse:
    return HealthResponse(status="ok", app=APP_TITLE, version=APP_VERSION)


@app.get("/ready", dependencies=[Depends(_require_api_key)])
def readiness(request: Request) -> dict[str, object]:
    return build_readiness_payload(getattr(request.app.state, "readiness", None))


@app.get("/capabilities", dependencies=[Depends(_require_api_key)])
def capabilities_endpoint() -> dict[str, object]:
    return build_capabilities_payload()


@app.get("/report/status", dependencies=[Depends(_require_api_key)])
def report_status_endpoint() -> dict[str, object]:
    return build_report_capability()


@app.get("/admin/feature-flags", dependencies=[Depends(_require_admin_feature_flags)])
def admin_feature_flags_get_endpoint() -> dict[str, object]:
    return {"success": True, **feature_flags_status()}


@app.patch("/admin/feature-flags", dependencies=[Depends(_require_admin_feature_flags)])
def admin_feature_flags_patch_endpoint(payload: dict[str, object], request: Request) -> dict[str, object]:
    try:
        updated = get_config_registry_service().legacy_patch(
            payload,
            request_id=_legacy_request_id(request),
        )
    except FeatureFlagValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, **updated, "capabilities_url": "/capabilities"}


@app.post("/admin/feature-flags/reset", dependencies=[Depends(_require_admin_feature_flags)])
def admin_feature_flags_reset_endpoint(request: Request) -> dict[str, object]:
    try:
        reset = get_config_registry_service().legacy_reset(request_id=_legacy_request_id(request))
    except FeatureFlagValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, **reset, "capabilities_url": "/capabilities"}


def _legacy_request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "").strip()
    if supplied and len(supplied) <= 128:
        return supplied
    return f"legacy-{uuid4().hex}"


@app.post("/retrieve", response_model=RetrieveResponse, dependencies=[Depends(_require_api_key)])
def retrieve_endpoint(payload: RetrieveRequest, cfg: AppConfig = Depends(get_cfg)) -> RetrieveResponse:
    try:
        if payload.include_query_plan:
            hits, latency_ms, plan = retrieve_only_with_plan(
                cfg,
                payload.query,
                topk=payload.top_k,
                neighbor_window=payload.neighbor_window,
            )
        else:
            hits, latency_ms = retrieve_only(
                cfg,
                payload.query,
                topk=payload.top_k,
                neighbor_window=payload.neighbor_window,
            )
            plan = None
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval failed: {exc}") from exc

    serialized_hits: list[RetrieveHit] = []
    for rank, hit in enumerate(hits, start=1):
        item = asdict(hit)
        if not payload.include_neighbors:
            item["neighbors"] = []
            item["expanded_text"] = ""
        item["rank"] = rank
        serialized_hits.append(RetrieveHit(**item))

    return RetrieveResponse(
        query=payload.query,
        top_k=payload.top_k,
        neighbor_window=payload.neighbor_window,
        latency_ms=latency_ms,
        hits=serialized_hits,
        context=build_context_view(hits) if payload.include_context else None,
        query_plan=plan.to_dict() if plan is not None and payload.include_query_plan else None,
    )


@app.post("/retrieve_context", response_model=RetrieveContextResponse, dependencies=[Depends(_require_api_key)])
def retrieve_context_endpoint(payload: RetrieveRequest, cfg: AppConfig = Depends(get_cfg)) -> RetrieveContextResponse:
    try:
        if payload.include_query_plan:
            hits, latency_ms, plan = retrieve_only_with_plan(
                cfg,
                payload.query,
                topk=payload.top_k,
                neighbor_window=payload.neighbor_window,
            )
        else:
            hits, latency_ms = retrieve_only(
                cfg,
                payload.query,
                topk=payload.top_k,
                neighbor_window=payload.neighbor_window,
            )
            plan = None
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval failed: {exc}") from exc

    return RetrieveContextResponse(
        query=payload.query,
        top_k=payload.top_k,
        neighbor_window=payload.neighbor_window,
        latency_ms=latency_ms,
        context=build_context_view(hits),
        hit_count=len(hits),
        query_plan=plan.to_dict() if plan is not None and payload.include_query_plan else None,
    )


@app.get("/openwebui/tool-spec", response_model=OpenWebUIToolSpecResponse, dependencies=[Depends(_require_api_key)])
def openwebui_tool_spec() -> OpenWebUIToolSpecResponse:
    return OpenWebUIToolSpecResponse(
        name="search_thermal_knowledge",
        description="Search the thermal-management knowledge base and return retrieved context for Open WebUI or a local LLM.",
        http_endpoint="/retrieve_context",
        auth="Bearer token via Authorization header when RAG_API_KEY is configured",
    )


@app.post("/agent/answer", response_model=AgentAnswerResponse, dependencies=[Depends(_require_api_key)])
def agent_answer_endpoint(payload: AgentAnswerRequest, agent: ThermalAgent = Depends(get_agent)) -> AgentAnswerResponse:
    request_options = {
        "engineering_project_id": payload.engineering_project_id,
        "reference_solver": payload.reference_solver.model_dump() if payload.reference_solver else None,
        "design_criteria": payload.design_criteria,
        "analysis_report_mode": payload.analysis_report_mode,
        "requested_outputs": payload.requested_outputs,
        "uploaded_model_file_id": payload.uploaded_model_file_id,
        "uploaded_model_filename": payload.uploaded_model_filename,
        "simulation_mode": payload.simulation_mode,
        "simulation_action": payload.simulation_action,
        "simulation_plan_id": payload.simulation_plan_id,
    }
    result = agent.answer(payload.query, session_id=payload.session_id, top_k=payload.top_k, request_options=request_options)
    return AgentAnswerResponse(**result)


@app.post("/agent/analyze", response_model=AgentAnalyzeResponse, dependencies=[Depends(_require_api_key)])
def agent_analyze_endpoint(payload: AgentAnalyzeRequest, agent: ThermalAgent = Depends(get_agent)) -> AgentAnalyzeResponse:
    analysis = agent.analyze(payload.query, session_id=payload.session_id)
    return AgentAnalyzeResponse(
        resolved_query=analysis.resolved_query,
        task=analysis.task.to_dict(),
        rewrite=analysis.rewrite.to_dict(),
    )


@app.post("/agent/analyze/export", response_model=AgentAnswerResponse, dependencies=[Depends(_require_api_key)])
def agent_analyze_export_endpoint(
    payload: AgentAnalyzeExportRequest,
    agent: ThermalAgent = Depends(get_agent),
) -> AgentAnswerResponse:
    if not payload.export_report:
        raise HTTPException(status_code=400, detail="export_report must be true for this endpoint.")

    export_formats = _normalize_export_formats(payload)
    unsupported = [item for item in export_formats if item != "md"]
    if unsupported:
        raise HTTPException(status_code=400, detail=f"Unsupported export format: {', '.join(unsupported)}")

    request_options = {
        "engineering_project_id": payload.engineering_project_id,
        "reference_solver": payload.reference_solver.model_dump() if payload.reference_solver else None,
        "design_criteria": payload.design_criteria,
        "analysis_report_mode": True,
        "requested_outputs": _ensure_report_output_requested(payload.requested_outputs),
        "uploaded_model_file_id": payload.uploaded_model_file_id,
        "uploaded_model_filename": payload.uploaded_model_filename,
    }
    result = agent.answer(
        payload.query,
        session_id=payload.session_id,
        top_k=payload.top_k,
        request_options=request_options,
    )

    metadata = dict(result.get("metadata") or {})
    report = _extract_report_metadata(metadata)
    report_content = report.get("content") if isinstance(report, dict) else None
    if not report.get("generated") or not isinstance(report_content, str) or not report_content.strip():
        raise HTTPException(status_code=500, detail="Analysis report content was not generated.")

    export_result = export_markdown_report(
        content=report_content,
        title=payload.title or report.get("title"),
        metadata={"sources": result.get("sources") or []},
        export_format="md",
    ).to_dict()
    if not export_result.get("generated"):
        status_code = 400 if export_result.get("errors") else 500
        raise HTTPException(status_code=status_code, detail=export_result)

    export_payload = _public_export_payload(export_result)
    result["metadata"] = _attach_report_export(metadata, report, export_payload)
    return AgentAnswerResponse(**result)


@app.get("/agent/reports/{report_id}/download", dependencies=[Depends(_require_api_key)])
def agent_report_download_endpoint(report_id: str, format: str = "md") -> FileResponse:
    report_path, error = resolve_exported_report_path(report_id=report_id, export_format=format)
    if error == "unsupported_format":
        raise HTTPException(status_code=400, detail="Only md report downloads are supported.")
    if error:
        raise HTTPException(status_code=400, detail="Invalid report_id.")
    if report_path is None or not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(
        path=report_path,
        media_type="text/markdown; charset=utf-8",
        filename=report_path.name,
    )


@app.post("/agent/memory/reset", dependencies=[Depends(_require_api_key)])
def agent_memory_reset_endpoint(payload: AgentMemoryResetRequest, agent: ThermalAgent = Depends(get_agent)) -> dict[str, str]:
    agent.reset_memory(payload.session_id)
    return {"status": "ok", "session_id": payload.session_id}


__all__ = [
    "APP_TITLE",
    "APP_VERSION",
    "UTF8JSONResponse",
    "app",
    "agent_analyze_export_endpoint",
    "agent_analyze_endpoint",
    "agent_answer_endpoint",
    "admin_feature_flags_get_endpoint",
    "admin_feature_flags_patch_endpoint",
    "admin_feature_flags_reset_endpoint",
    "agent_report_download_endpoint",
    "agent_memory_reset_endpoint",
    "build_capabilities_payload",
    "build_report_capability",
    "capabilities_endpoint",
    "get_agent",
    "get_cfg",
    "health",
    "lifespan",
    "openwebui_tool_spec",
    "report_status_endpoint",
    "retrieve_context_endpoint",
    "retrieve_endpoint",
    "readiness",
]
