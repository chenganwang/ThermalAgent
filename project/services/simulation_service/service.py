from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from .adapters.base import SimulationAdapter
from .adapters.matlab_adapter import MatlabAdapter
from .adapters.mock_adapter import MockAdapter
from .contracts import (
    SIMULATION_STATUS_FAILED,
    SIMULATION_STATUS_MISSING_PARAMS,
    SimulationAdapterResult,
    SimulationResultEnvelope,
    SimulationRunRequest,
)
from .config import SimulationConfig, load_simulation_config
from .history import InMemorySimulationHistoryRepository
from .history_backends.base import SimulationHistoryBackend
from .history_backends.repository import build_history_backend
from .parser import SimulationResultParser
from .registry import DEFAULT_SIMULATION_REGISTRY, SimulationRegistry
from .schema import SimulationHistoryRecord


class SimulationService:
    """Unique execution entrance for Phase 1 simulation runs."""

    def __init__(
        self,
        *,
        registry: SimulationRegistry | None = None,
        adapters: dict[str, SimulationAdapter] | None = None,
        parser: SimulationResultParser | None = None,
        history: InMemorySimulationHistoryRepository | None = None,
        history_backend: SimulationHistoryBackend | None = None,
        default_adapter: str | None = None,
        config: SimulationConfig | None = None,
    ) -> None:
        self.config = config or load_simulation_config()
        self.registry = registry or DEFAULT_SIMULATION_REGISTRY
        self.adapters = adapters or {
            "mock": MockAdapter(),
            "matlab": MatlabAdapter(engine=None),
        }
        self.parser = parser or SimulationResultParser()
        self.history = history or InMemorySimulationHistoryRepository()
        self.history_backend = history_backend or build_history_backend(self.config)
        self.default_adapter = (
            default_adapter
            or os.getenv("SIMULATION_DEFAULT_BACKEND")
            or os.getenv("SIMULATION_DEFAULT_ADAPTER")
            or self.config.default_backend
            or "mock"
        ).strip().lower()

    @classmethod
    def default(cls) -> "SimulationService":
        return cls()

    def list_tools(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self.registry.list()]

    def get_tool(self, tool_name: str) -> dict[str, Any] | None:
        spec = self.registry.get(tool_name)
        return spec.to_dict() if spec is not None else None

    def describe_status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "default_adapter": self.default_adapter,
            "history_backend": self.config.history_backend,
            "history_backend_status": self.history_backend.health_check(),
            "available_adapters": [adapter.describe() for adapter in self.adapters.values()],
        }

    def list_adapter_statuses(self) -> list[dict[str, Any]]:
        return [adapter.health_check().to_dict() for adapter in self.adapters.values()]

    def create_task(self, request: SimulationRunRequest) -> dict[str, Any]:
        task_id = self.history.create_task(request)
        return {"task_id": task_id, "status": "created", "request": request.to_dict()}

    def run(self, request: SimulationRunRequest) -> SimulationResultEnvelope:
        request = self._normalize_request(request)
        run_id = _id("sim-run")
        started_at = _now()
        started = perf_counter()
        try:
            spec = self.registry.require(request.tool_name)
        except KeyError:
            return self._error_envelope(
                request=request,
                run_id=run_id,
                started_at=started_at,
                elapsed_ms=_elapsed(started),
                status=SIMULATION_STATUS_FAILED,
                code="unknown_tool",
                message=f"Unknown simulation tool: {request.tool_name}",
            )
        if not spec.enabled:
            return self._error_envelope(
                request=request,
                run_id=run_id,
                started_at=started_at,
                elapsed_ms=_elapsed(started),
                status=SIMULATION_STATUS_FAILED,
                code="disabled_tool",
                message=f"Simulation tool is disabled: {request.tool_name}",
            )

        missing = self._missing_inputs(request.inputs, spec.required_inputs)
        if missing:
            return self._error_envelope(
                request=request,
                run_id=run_id,
                started_at=started_at,
                elapsed_ms=_elapsed(started),
                status=SIMULATION_STATUS_MISSING_PARAMS,
                code="missing_params",
                message="Simulation request is missing required inputs.",
                extra={"missing": missing},
            )

        requested_adapter = request.adapter_name or self.default_adapter or spec.default_adapter
        selected_adapter_name = self._select_adapter_name(request.mode, requested_adapter)
        warnings: list[str] = []
        metadata = {
            "requested_adapter": requested_adapter,
            "selected_adapter": selected_adapter_name,
            "mode": request.mode,
            "tool_spec_version": spec.version,
            "cfd_executed": False,
            "solver_executed": False,
        }

        if selected_adapter_name not in spec.supported_adapters:
            return self._error_envelope(
                request=request,
                run_id=run_id,
                started_at=started_at,
                elapsed_ms=_elapsed(started),
                status=SIMULATION_STATUS_FAILED,
                code="unsupported_adapter",
                message=f"Adapter {selected_adapter_name} is not supported by {spec.tool_name}.",
                extra={"supported_adapters": spec.supported_adapters},
            )

        adapter = self.adapters.get(selected_adapter_name)
        if adapter is None:
            return self._error_envelope(
                request=request,
                run_id=run_id,
                started_at=started_at,
                elapsed_ms=_elapsed(started),
                status=SIMULATION_STATUS_FAILED,
                code="adapter_not_registered",
                message=f"Adapter {selected_adapter_name} is not registered.",
            )

        if selected_adapter_name != "mock" and not adapter.is_available() and spec.supports_mock and request.allow_mock:
            warnings.extend(["fallback_to_mock", f"{selected_adapter_name}_adapter_unavailable"])
            selected_adapter_name = "mock"
            metadata["selected_adapter"] = selected_adapter_name
            adapter = self.adapters["mock"]

        task_id = self.history.create_task(request)
        job_id = self.history.start_job(task_id=task_id, adapter_name=selected_adapter_name)
        adapter_result = adapter.execute(request, spec)
        event_history_id = self.history.finish_job(
            task_id=task_id,
            job_id=job_id,
            status=adapter_result.status,
            result=adapter_result.to_dict(),
        )
        record_history_id = _id("sim-history")
        if request.options.get("replay_of_run_id"):
            metadata["replay_of_run_id"] = request.options["replay_of_run_id"]
        envelope = self.parser.parse(
            request=request,
            adapter_result=adapter_result,
            task_id=task_id,
            job_id=job_id,
            history_id=record_history_id or event_history_id,
            run_id=run_id,
            metadata=metadata,
            warnings=warnings,
            started_at=started_at,
            finished_at=_now(),
            elapsed_ms=_elapsed(started),
        )
        history_error = self._append_history_record(record_history_id, request, envelope)
        if history_error:
            envelope = replace(
                envelope,
                warnings=[*envelope.warnings, "simulation_history_append_failed"],
                metadata={**envelope.metadata, "history_append_error": history_error},
            )
        return envelope

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self.history.get_task(task_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.history.get_job(job_id)

    def list_history(self, task_id: str | None = None) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.history.list_events(task_id)]

    def list_history_records(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        tool_name: str | None = None,
        adapter_name: str | None = None,
        trace_id: str | None = None,
        is_mock: bool | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            record.to_dict()
            for record in self.history_backend.list(
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
        ]

    def get_history_record(self, run_id: str) -> dict[str, Any] | None:
        record = self.history_backend.get(run_id)
        return record.to_dict() if record is not None else None

    def get_result(self, run_id: str) -> dict[str, Any] | None:
        record = self.history_backend.get(run_id)
        if record is None:
            return None
        return dict(record.result)

    def replay_task(self, task_id: str) -> SimulationResultEnvelope:
        return self.run(self.history.replay_task(task_id))

    def replay_run(self, run_id: str) -> SimulationResultEnvelope:
        record = self.history_backend.get(run_id)
        if record is None:
            raise KeyError(f"Unknown simulation run: {run_id}")
        request_data = dict(record.request)
        request = SimulationRunRequest(
            tool_name=str(request_data.get("tool_name")),
            inputs=dict(request_data.get("inputs") or {}),
            session_id=request_data.get("session_id"),
            user_query=request_data.get("user_query"),
            adapter_name="mock",
            mode="mock",
            timeout_seconds=request_data.get("timeout_seconds"),
            options={**dict(request_data.get("options") or {}), "replay_of_run_id": run_id},
            parameters=dict(request_data.get("parameters") or {}),
            units=dict(request_data.get("units") or {}),
            config=dict(request_data.get("config") or {}),
            requested_backend="mock",
            allow_mock=True,
            trace_id=request_data.get("trace_id"),
            metadata=dict(request_data.get("metadata") or {}),
        )
        return self.run(request)

    def list_models(self) -> dict[str, Any]:
        return {"models": [], "warnings": ["no_runtime_models_registered"]}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            return {"status": "not_found", "job_id": job_id, "cancelled": False}
        return {
            "status": "unsupported",
            "job_id": job_id,
            "cancelled": False,
            "message": "Phase 1 jobs are synchronous and cannot be cancelled.",
        }

    def _select_adapter_name(self, mode: str | None, requested_adapter: str) -> str:
        normalized_mode = (mode or "mock").strip().lower()
        if normalized_mode == "mock":
            return "mock"
        return (requested_adapter or self.default_adapter or "mock").strip().lower()

    def _normalize_request(self, request: SimulationRunRequest) -> SimulationRunRequest:
        inputs = dict(request.inputs or {})
        if request.parameters and "parameters" not in inputs:
            inputs["parameters"] = dict(request.parameters)
        if request.config and "config" not in inputs:
            inputs["config"] = dict(request.config)
        requested = request.requested_backend or request.adapter_name
        return SimulationRunRequest(
            tool_name=request.tool_name,
            inputs=inputs,
            session_id=request.session_id,
            user_query=request.user_query,
            adapter_name=request.adapter_name or requested,
            mode=request.mode,
            timeout_seconds=request.timeout_seconds,
            options=dict(request.options or {}),
            parameters=dict(request.parameters or {}),
            units=dict(request.units or {}),
            config=dict(request.config or {}),
            requested_backend=requested,
            allow_mock=request.allow_mock,
            trace_id=request.trace_id or _id("sim-trace"),
            metadata=dict(request.metadata or {}),
        )

    def _missing_inputs(self, inputs: dict[str, Any], required: list[str]) -> list[str]:
        values = dict(inputs or {})
        return [name for name in required if name not in values or values[name] in (None, "", [])]

    def _error_envelope(
        self,
        *,
        request: SimulationRunRequest,
        run_id: str,
        started_at: str,
        elapsed_ms: int,
        status: str,
        code: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> SimulationResultEnvelope:
        task_id = f"sim-task-{uuid4().hex}"
        error = {"code": code, "message": message}
        if extra:
            error.update(extra)
        adapter_result = SimulationAdapterResult(
            tool_name=request.tool_name,
            adapter_name=request.adapter_name or self.default_adapter or "mock",
            status=status,
            mocked=False,
            raw_result={},
            errors=[error],
            metadata={"cfd_executed": False, "solver_executed": False},
        )
        history_id = _id("sim-history")
        envelope = self.parser.parse(
            request=request,
            adapter_result=adapter_result,
            task_id=task_id,
            job_id=None,
            history_id=history_id,
            run_id=run_id,
            metadata={
                "requested_adapter": request.adapter_name,
                "selected_adapter": adapter_result.adapter_name,
                "mode": request.mode,
                "cfd_executed": False,
                "solver_executed": False,
            },
            started_at=started_at,
            finished_at=_now(),
            elapsed_ms=elapsed_ms,
        )
        history_error = self._append_history_record(history_id, request, envelope)
        if history_error:
            envelope = replace(
                envelope,
                warnings=[*envelope.warnings, "simulation_history_append_failed"],
                metadata={**envelope.metadata, "history_append_error": history_error},
            )
        return envelope

    def _append_history_record(self, history_id: str, request: SimulationRunRequest, envelope: SimulationResultEnvelope) -> dict[str, Any] | None:
        data = envelope.to_dict()
        first_error = envelope.errors[0] if envelope.errors else None
        try:
            self.history_backend.append(
                SimulationHistoryRecord(
                    history_id=history_id,
                    run_id=envelope.run_id or _id("sim-run"),
                    task_id=envelope.task_id,
                    user_query=request.user_query,
                    request=request.to_dict(),
                    result=data,
                    status=envelope.status,
                    error=first_error,
                    trace_id=envelope.trace_id,
                    metadata={"tool_name": envelope.tool_name, "adapter_name": envelope.adapter_name},
                )
            )
        except Exception as exc:
            return {"code": "simulation_history_append_failed", "message": str(exc)}
        return None


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed(started: float) -> int:
    return int((perf_counter() - started) * 1000)


__all__ = ["SimulationService"]
