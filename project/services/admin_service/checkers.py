from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from threading import Lock
from time import monotonic, perf_counter
from typing import Any, Iterable

from .contracts import AdminCheckContext, CheckOutcome, ModuleDescriptor, ModuleHealth
from .redaction import sanitize_admin_value


_SYSTEM_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SafeCheckRunner:
    """Runs registered read-only checkers with timeout, cache and failure isolation."""

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="admin-check")
        self._cache: dict[str, tuple[float, ModuleHealth]] = {}
        self._lock = Lock()

    def check(self, descriptor: ModuleDescriptor, context: AdminCheckContext, *, force: bool = False) -> ModuleHealth:
        cached = self._cached(descriptor, force=force)
        if cached is not None:
            return cached
        future = self._executor.submit(self._run_checker, descriptor, context)
        return self._resolve_future(descriptor, future)

    def check_all(
        self,
        descriptors: Iterable[ModuleDescriptor],
        context: AdminCheckContext,
        *,
        force: bool = False,
    ) -> list[ModuleHealth]:
        ordered = list(descriptors)
        results: dict[str, ModuleHealth] = {}
        pending: dict[str, tuple[ModuleDescriptor, Future[ModuleHealth]]] = {}
        for descriptor in ordered:
            cached = self._cached(descriptor, force=force)
            if cached is not None:
                results[descriptor.module_id] = cached
            else:
                pending[descriptor.module_id] = (
                    descriptor,
                    self._executor.submit(self._run_checker, descriptor, context),
                )
        for module_id, (descriptor, future) in pending.items():
            results[module_id] = self._resolve_future(descriptor, future)
        return [results[item.module_id] for item in ordered]

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _cached(self, descriptor: ModuleDescriptor, *, force: bool) -> ModuleHealth | None:
        if force:
            return None
        with self._lock:
            item = self._cache.get(descriptor.module_id)
        if item is None or monotonic() - item[0] > descriptor.cache_ttl_seconds:
            return None
        return item[1].model_copy(deep=True)

    def _resolve_future(self, descriptor: ModuleDescriptor, future: Future[ModuleHealth]) -> ModuleHealth:
        try:
            result = future.result(timeout=descriptor.timeout_seconds)
        except FutureTimeoutError:
            result = _failure_health(
                descriptor,
                code="CHECK_TIMEOUT",
                message="The bounded read-only checker timed out.",
                status="unknown",
                retryable=True,
            )
        except Exception:
            result = _failure_health(
                descriptor,
                code="CHECK_FAILED",
                message="The read-only checker failed without affecting other modules.",
                status="unhealthy" if not descriptor.optional else "degraded",
            )
        with self._lock:
            self._cache[descriptor.module_id] = (monotonic(), result)
        return result.model_copy(deep=True)

    @staticmethod
    def _run_checker(descriptor: ModuleDescriptor, context: AdminCheckContext) -> ModuleHealth:
        started = perf_counter()
        observed_at = utc_now_iso()
        outcome = descriptor.checker(context)
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        return _health_from_outcome(descriptor, outcome, observed_at=observed_at, latency_ms=latency_ms)


def _health_from_outcome(
    descriptor: ModuleDescriptor,
    outcome: CheckOutcome,
    *,
    observed_at: str,
    latency_ms: int,
) -> ModuleHealth:
    status = outcome.status or _derive_status(outcome)
    severity = outcome.severity or _derive_severity(status, descriptor.optional)
    healthy = outcome.healthy
    if status == "disabled":
        healthy = None
    return ModuleHealth(
        module_id=descriptor.module_id,
        name=descriptor.name,
        category=descriptor.category,
        configured=outcome.configured,
        enabled=outcome.enabled,
        available=outcome.available,
        ready=outcome.ready,
        healthy=healthy,
        status=status,
        severity=severity,
        experimental=descriptor.experimental,
        optional=descriptor.optional,
        last_check_at=observed_at,
        last_success_at=observed_at if healthy is True else None,
        latency_ms=latency_ms,
        stale_after_seconds=descriptor.stale_after_seconds,
        dependencies=list(descriptor.dependencies),
        metrics=sanitize_admin_value(outcome.metrics),
        error_code=outcome.error_code,
        message=str(sanitize_admin_value(outcome.message or _default_message(status))),
        next_action=str(sanitize_admin_value(outcome.next_action)) if outcome.next_action else None,
        source=descriptor.source,
        observed_at=observed_at,
        side_effects=[],
    )


def _failure_health(
    descriptor: ModuleDescriptor,
    *,
    code: str,
    message: str,
    status: str,
    retryable: bool = False,
) -> ModuleHealth:
    now = utc_now_iso()
    return _health_from_outcome(
        descriptor,
        CheckOutcome(
            configured=True,
            enabled=True,
            available=None,
            ready=False,
            healthy=False if status in {"unhealthy", "degraded"} else None,
            status=status,
            error_code=code,
            message=message,
            metrics={"retryable": retryable},
        ),
        observed_at=now,
        latency_ms=max(1, round(descriptor.timeout_seconds * 1000)) if code == "CHECK_TIMEOUT" else 0,
    )


def _derive_status(outcome: CheckOutcome) -> str:
    if not outcome.enabled:
        return "disabled"
    if outcome.available is False:
        return "unavailable"
    if outcome.healthy is False:
        return "unhealthy"
    if outcome.ready is False:
        return "degraded"
    if outcome.available is None or outcome.ready is None or outcome.healthy is None:
        return "unknown"
    return "healthy"


def _derive_severity(status: str, optional: bool) -> str:
    if status == "healthy":
        return "info"
    if status == "disabled":
        return "info"
    if status in {"unknown", "checking", "degraded"} or optional:
        return "warning"
    return "critical"


def _default_message(status: str) -> str:
    return {
        "healthy": "The bounded read-only check completed successfully.",
        "disabled": "The module is disabled by policy and is not considered unhealthy.",
        "unknown": "Health has not been proven by a safe Phase A probe.",
        "unavailable": "The module is unavailable.",
        "degraded": "The module is only partially ready.",
        "unhealthy": "The module failed its bounded read-only check.",
    }.get(status, "Module status is available.")


def application_checker(context: AdminCheckContext) -> CheckOutcome:
    routes = [route for route in context.app.routes if getattr(route, "path", "") not in _SYSTEM_ROUTES]
    legacy_routes = [route for route in routes if not getattr(route, "path", "").startswith("/admin/api/v1")]
    admin_routes = [route for route in routes if getattr(route, "path", "").startswith("/admin/api/v1")]
    return CheckOutcome(
        available=True,
        ready=True,
        healthy=True,
        metrics={
            "legacy_business_route_count": len(legacy_routes),
            "admin_phase_a_route_count": len(admin_routes),
            "request_id_enabled": True,
        },
        message="FastAPI application and the additive Admin router are registered.",
    )


def mysql_checker(context: AdminCheckContext) -> CheckOutcome:
    state = context.app.state
    db = getattr(state, "db", None)
    db_error = getattr(state, "db_error", None)
    configured = bool(context.cfg.mysql.host and context.cfg.mysql.database and context.cfg.mysql.user)
    if db_error:
        return CheckOutcome(
            configured=configured,
            available=False,
            ready=False,
            healthy=False,
            status="unavailable",
            error_code="DB_UNAVAILABLE",
            metrics={"probe_mode": "startup_state_only", "sql_executed": False},
            message="Database initialization was not successful; no SQL was executed by Admin Phase A.",
            next_action="Check deployment database connectivity outside the Admin request path.",
        )
    if db is not None:
        return CheckOutcome(
            configured=configured,
            available=True,
            ready=None,
            healthy=None,
            status="unknown",
            metrics={"pool_initialized": True, "probe_mode": "startup_state_only", "sql_executed": False},
            message="A database pool exists, but Phase A did not execute a live SQL health query.",
        )
    return CheckOutcome(
        configured=configured,
        available=None,
        ready=None,
        healthy=None,
        status="unknown",
        metrics={"pool_initialized": False, "probe_mode": "not_checked", "sql_executed": False},
        message="Database health is not checked because the application lifespan state is unavailable.",
    )


def faiss_checker(context: AdminCheckContext) -> CheckOutcome:
    return _index_metadata_checker(
        artifact=context.cfg.paths.faiss_index_path,
        metadata=context.cfg.paths.faiss_meta_path,
        count_keys=("ntotal", "chunk_count"),
        extra_keys=("dim", "normalize"),
        name="FAISS",
    )


def bm25_checker(context: AdminCheckContext) -> CheckOutcome:
    return _index_metadata_checker(
        artifact=context.cfg.paths.bm25_corpus_path,
        metadata=context.cfg.paths.bm25_meta_path,
        count_keys=("chunk_count",),
        extra_keys=("enabled", "k1", "b"),
        name="BM25",
    )


def _index_metadata_checker(
    *,
    artifact: Path,
    metadata: Path,
    count_keys: tuple[str, ...],
    extra_keys: tuple[str, ...],
    name: str,
) -> CheckOutcome:
    artifact_exists = artifact.is_file()
    metadata_exists = metadata.is_file()
    if not artifact_exists or not metadata_exists:
        return CheckOutcome(
            available=False,
            ready=False,
            healthy=False,
            status="unavailable",
            error_code="INDEX_MISSING",
            metrics={
                "artifact_exists": artifact_exists,
                "metadata_exists": metadata_exists,
                "index_loaded": False,
                "index_rebuilt": False,
            },
            message=f"{name} index artifact or metadata is missing; no load or rebuild was attempted.",
        )
    payload = _read_metadata(metadata)
    if payload is None:
        return CheckOutcome(
            available=False,
            ready=False,
            healthy=False,
            status="unavailable",
            error_code="INDEX_METADATA_INVALID",
            metrics={"artifact_exists": True, "metadata_exists": True, "index_rebuilt": False},
            message=f"{name} metadata is unreadable; the index was not loaded or rebuilt.",
        )
    metrics: dict[str, Any] = {
        "artifact_exists": True,
        "metadata_exists": True,
        "artifact_size_bytes": artifact.stat().st_size,
        "consistency_checked": False,
        "index_loaded": False,
        "index_rebuilt": False,
    }
    for key in (*count_keys, *extra_keys):
        if key in payload and isinstance(payload[key], (str, int, float, bool)):
            metrics[key] = payload[key]
    return CheckOutcome(
        available=True,
        ready=True,
        healthy=None,
        status="unknown",
        metrics=metrics,
        message=f"{name} artifacts exist; database consistency remains not checked in the safe metadata probe.",
    )


def retrieval_checker(context: AdminCheckContext) -> CheckOutcome:
    faiss_exists = context.cfg.paths.faiss_index_path.is_file()
    bm25_exists = context.cfg.paths.bm25_corpus_path.is_file()
    available = faiss_exists or bm25_exists
    return CheckOutcome(
        available=available,
        ready=available,
        healthy=None,
        status="unknown" if available else "unavailable",
        error_code=None if available else "INDEX_MISSING",
        metrics={
            "faiss_artifact_exists": faiss_exists,
            "bm25_artifact_exists": bm25_exists,
            "smoke_test_run": False,
            "external_llm_called": False,
        },
        message=(
            "Retrieval code and at least one index artifact are present; no query or external model was called."
            if available
            else "Retrieval index artifacts are unavailable; no rebuild was attempted."
        ),
    )


def agent_checker(context: AdminCheckContext) -> CheckOutcome:
    agent_initialized = getattr(context.app.state, "agent", None) is not None
    return CheckOutcome(
        available=True,
        ready=True if agent_initialized else None,
        healthy=None,
        status="unknown",
        metrics={
            "agent_initialized": agent_initialized,
            "answer_probe_run": False,
            "external_llm_called": False,
        },
        message="Agent implementation is registered; Phase A does not call the Agent or any external model for health checks.",
    )


def tool_registry_checker(_context: AdminCheckContext) -> CheckOutcome:
    from services.retrieval_service.tools.specs import TOOL_SPECS

    return CheckOutcome(
        available=True,
        ready=True,
        healthy=bool(TOOL_SPECS),
        metrics={"registered_tool_count": len(TOOL_SPECS), "tools_executed": False},
        message="The deterministic tool registry was inspected without executing any tool.",
    )


def simulation_service_checker(_context: AdminCheckContext) -> CheckOutcome:
    from services.simulation_service.api import get_simulation_service

    service = get_simulation_service()
    enabled = bool(service.config.enabled)
    return CheckOutcome(
        configured=True,
        enabled=enabled,
        available=True,
        ready=None if enabled else False,
        healthy=None,
        status="unknown" if enabled else "disabled",
        metrics={
            "default_adapter": service.default_adapter,
            "history_backend": service.config.history_backend,
            "registered_tool_count": len(service.registry.list()),
            "simulation_run_called": False,
            "cfd_run_called": False,
        },
        message=(
            "Simulation inventory is registered; no simulation or CFD run was started."
            if enabled
            else "Simulation is disabled by policy; no simulation or CFD run was started."
        ),
    )


def scenario_catalog_checker(_context: AdminCheckContext) -> CheckOutcome:
    service = _catalog_service()
    count = len(service.scenarios.list())
    return CheckOutcome(
        available=True,
        ready=True,
        healthy=count > 0,
        metrics={"scenario_count": count, "catalog_reloaded": False},
        message="The static scenario catalog was inspected without reload or execution.",
    )


def model_registry_checker(_context: AdminCheckContext) -> CheckOutcome:
    service = _catalog_service()
    count = len(service.models.list())
    return CheckOutcome(
        available=True,
        ready=True,
        healthy=count > 0,
        metrics={"model_count": count, "registry_modified": False},
        message="The model registry was inspected without approval, registration, or execution.",
    )


def executor_registry_checker(_context: AdminCheckContext) -> CheckOutcome:
    service = _catalog_service()
    items = service.executors.list()
    return CheckOutcome(
        available=True,
        ready=True,
        healthy=bool(items),
        metrics={"executor_count": len(items), "executor_invoked": False},
        message="The controlled executor registry was inspected without invoking an executor.",
    )


def _catalog_service() -> Any:
    from services.simulation_service.catalog import get_catalog_service

    return get_catalog_service()


def matlab_checker(_context: AdminCheckContext) -> CheckOutcome:
    from services.simulation_service.matlab.adapter import MatlabSimulationAdapter

    status_payload = MatlabSimulationAdapter().status().to_dict()
    enabled = bool(status_payload.get("enabled"))
    available = bool(status_payload.get("available")) if enabled else bool(status_payload.get("root_exists"))
    if not enabled:
        status = "disabled"
        ready: bool | None = False
        healthy: bool | None = None
    else:
        ready = bool(status_payload.get("api_enabled") and status_payload.get("engine_importable"))
        healthy = None
        status = "unknown" if available else "unavailable"
    return CheckOutcome(
        configured=bool(status_payload.get("root_exists") or status_payload.get("engine_importable")),
        enabled=enabled,
        available=available,
        ready=ready,
        healthy=healthy,
        status=status,
        metrics={
            "engine_importable": bool(status_payload.get("engine_importable")),
            "engine_start_allowed": bool(status_payload.get("engine_start_allowed")),
            "api_enabled": bool(status_payload.get("api_enabled")),
            "engine_started": False,
        },
        message="MATLAB discovery/status was read with engine startup explicitly absent.",
    )


def report_service_checker(context: AdminCheckContext) -> CheckOutcome:
    base = context.project_root / "services" / "retrieval_service" / "analysis"
    builder = (base / "report_builder.py").is_file()
    exporter = (base / "report_exporter.py").is_file()
    available = builder and exporter
    report_root = context.project_root / "reports" / "analysis"
    stats = _bounded_tree_stats(report_root, max_files=500)
    return CheckOutcome(
        available=available,
        ready=available,
        healthy=None,
        status="unknown" if available else "unavailable",
        error_code=None if available else "REPORT_BACKEND_UNAVAILABLE",
        metrics={
            "builder_present": builder,
            "exporter_present": exporter,
            "stored_report_count": stats["file_count"],
            "report_generated": False,
        },
        message="Report inventory was inspected without generating, validating, archiving, or deleting a report.",
    )


def model_assets_checker(context: AdminCheckContext) -> CheckOutcome:
    from services.simulation_service.model_assets.config import load_model_asset_config
    from services.simulation_service.model_assets.registry import ModelAssetRegistry

    config = load_model_asset_config(context.project_root)
    assets = ModelAssetRegistry(config).list()
    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.status] = counts.get(asset.status, 0) + 1
    enabled = bool(config.upload_enabled or config.admin_enabled)
    return CheckOutcome(
        configured=True,
        enabled=enabled,
        available=config.metadata_dir.exists() or not enabled,
        ready=None if enabled else False,
        healthy=None,
        status="unknown" if enabled else "disabled",
        metrics={
            "asset_count": len(assets),
            "pending_review_count": counts.get("pending_review", 0),
            "counts_by_status": counts,
            "asset_modified": False,
        },
        message="Model asset metadata was read without upload, approval, registration, or state change.",
    )


def evidence_storage_checker(context: AdminCheckContext) -> CheckOutcome:
    root = context.project_root / "runtime" / "simulation"
    stats = _bounded_tree_stats(root, max_files=1000, suffixes={".json", ".md", ".jsonl"})
    exists = root.is_dir()
    return CheckOutcome(
        available=exists,
        ready=exists,
        healthy=True if exists else None,
        status="healthy" if exists else "unavailable",
        metrics={**stats, "files_modified": False},
        message="Fixed-root evidence metadata was counted without reading content or modifying files.",
    )


def runtime_storage_checker(context: AdminCheckContext) -> CheckOutcome:
    root = context.project_root / "runtime"
    stats = _bounded_tree_stats(root, max_files=2000)
    exists = root.is_dir()
    free_bytes = shutil.disk_usage(root if exists else context.project_root).free
    healthy = bool(exists and free_bytes >= 100 * 1024 * 1024)
    return CheckOutcome(
        available=exists,
        ready=exists,
        healthy=healthy,
        status="healthy" if healthy else ("degraded" if exists else "unavailable"),
        metrics={**stats, "free_bytes": free_bytes, "files_modified": False},
        error_code=None if healthy else "RUNTIME_STORAGE_LOW_OR_UNAVAILABLE",
        message="Runtime storage was inspected with bounded metadata-only traversal; no file was changed or deleted.",
    )


def _read_metadata(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _bounded_tree_stats(
    root: Path,
    *,
    max_files: int,
    suffixes: set[str] | None = None,
) -> dict[str, Any]:
    if not root.is_dir():
        return {"file_count": 0, "bytes": 0, "truncated": False}
    count = 0
    total_bytes = 0
    truncated = False
    try:
        for current_root, _dirs, files in os.walk(root):
            for name in files:
                path = Path(current_root) / name
                if suffixes is not None and path.suffix.lower() not in suffixes:
                    continue
                count += 1
                if count > max_files:
                    truncated = True
                    break
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    continue
            if truncated:
                break
    except OSError:
        truncated = True
    return {"file_count": min(count, max_files), "bytes": total_bytes, "truncated": truncated}


def build_module_descriptors() -> tuple[ModuleDescriptor, ...]:
    return (
        ModuleDescriptor("backend", "Backend API", "core", application_checker, source="fastapi_route_registry"),
        ModuleDescriptor("mysql", "MySQL", "data", mysql_checker, source="application_lifespan_state"),
        ModuleDescriptor("faiss", "FAISS Index", "retrieval", faiss_checker, dependencies=("mysql",), source="index_metadata"),
        ModuleDescriptor("bm25", "BM25 Index", "retrieval", bm25_checker, dependencies=("mysql",), source="index_metadata"),
        ModuleDescriptor("retrieval", "Retrieval", "retrieval", retrieval_checker, dependencies=("mysql", "faiss", "bm25"), source="component_inventory"),
        ModuleDescriptor("agent", "Thermal Agent", "agent", agent_checker, dependencies=("retrieval",), source="application_lifespan_state"),
        ModuleDescriptor("tool_registry", "Tool Registry", "agent", tool_registry_checker, dependencies=("agent",), source="static_tool_registry"),
        ModuleDescriptor("simulation_service", "Simulation Service", "simulation", simulation_service_checker, experimental=True, optional=True, source="simulation_config_registry"),
        ModuleDescriptor("matlab", "MATLAB", "simulation", matlab_checker, dependencies=("simulation_service",), experimental=True, optional=True, timeout_seconds=3.0, source="matlab_safe_status"),
        ModuleDescriptor("scenario_catalog", "Scenario Catalog", "simulation", scenario_catalog_checker, dependencies=("simulation_service",), experimental=True, optional=True, source="static_scenario_catalog"),
        ModuleDescriptor("model_registry", "Model Registry", "simulation", model_registry_checker, dependencies=("scenario_catalog",), experimental=True, optional=True, source="controlled_model_registry"),
        ModuleDescriptor("executor_registry", "Executor Registry", "simulation", executor_registry_checker, dependencies=("model_registry",), experimental=True, optional=True, source="controlled_executor_registry"),
        ModuleDescriptor("report_service", "Report Service", "report", report_service_checker, experimental=True, optional=True, source="report_inventory"),
        ModuleDescriptor("model_assets", "Model Assets", "simulation", model_assets_checker, experimental=True, optional=True, source="model_asset_metadata"),
        ModuleDescriptor("evidence_storage", "Evidence Storage", "storage", evidence_storage_checker, optional=True, source="bounded_storage_metadata"),
        ModuleDescriptor("runtime_storage", "Runtime Storage", "storage", runtime_storage_checker, source="bounded_storage_metadata"),
    )


__all__ = ["SafeCheckRunner", "build_module_descriptors", "utc_now_iso"]
