from __future__ import annotations

from collections.abc import Callable
from typing import Any

from services.simulation_service.catalog.service import run_simulation
from services.simulation_service.catalog.model_registry import ModelRegistry
from services.simulation_service.matlab.runtime import MatlabRuntimeManager, get_matlab_runtime_manager
from services.simulation_service.matlab.runtime import DEFAULT_ALLOWED_MODELS, MATLAB_DISPATCHER
from services.simulation_service.matlab.schemas import MatlabExecutionRequest
from services.simulation_service.modeling.compiler import GeneratedModelArtifactStore
from services.simulation_service.modeling.lifecycle import GeneratedModelLifecycleError, GeneratedModelService
from services.simulation_service.modeling.result_critic import GeneratedSimulationResultCritic

from .simulation_mode_contracts import SimulationExecutionResult, SimulationPlan


class ConfirmedSimulationExecutor:
    def __init__(
        self,
        *,
        matlab_runtime: MatlabRuntimeManager | Any | None = None,
        python_runner: Callable[..., dict[str, Any]] | None = None,
        generated_model_service: GeneratedModelService | None = None,
        generated_artifact_store: GeneratedModelArtifactStore | None = None,
        result_critic: GeneratedSimulationResultCritic | None = None,
        operation_recorder: Any | None = None,
    ) -> None:
        self.matlab_runtime = matlab_runtime or get_matlab_runtime_manager()
        self.python_runner = python_runner or run_simulation
        self.generated_model_service = generated_model_service or GeneratedModelService()
        self.generated_artifact_store = generated_artifact_store or GeneratedModelArtifactStore()
        self.result_critic = result_critic or GeneratedSimulationResultCritic()
        self.operation_recorder = operation_recorder

    def execute(self, plan: SimulationPlan, *, confirmed: bool) -> SimulationExecutionResult:
        if not confirmed:
            return self._blocked(plan, "SIMULATION_PLAN_NOT_CONFIRMED", "Explicit confirmation is required.")
        if not plan.execution_allowed:
            return self._blocked(
                plan,
                plan.execution_block_reason or "SIMULATION_EXECUTION_NOT_ALLOWED",
                "The reviewed plan is not executable.",
            )
        if plan.model_source == "generated":
            return self._execute_generated(plan)
        if plan.solver_backend == "matlab" and (
            plan.model_id not in DEFAULT_ALLOWED_MODELS or plan.matlab_entrypoint != MATLAB_DISPATCHER
        ):
            return self._blocked(plan, "MATLAB_MODEL_NOT_FOUND", "MATLAB model or entrypoint is not allow-listed.")
        if plan.solver_backend == "matlab":
            return self._execute_matlab(plan)
        if plan.solver_backend == "python":
            return self._execute_python(plan)
        return self._blocked(plan, "SIMULATION_BACKEND_NOT_EXECUTABLE", "The selected backend is preparation-only.")

    def _execute_generated(self, plan: SimulationPlan) -> SimulationExecutionResult:
        if not plan.generated_model_id:
            return self._blocked(plan, "GENERATED_MODEL_NOT_FOUND", "Generated-model identity is missing.")
        try:
            with self.generated_model_service.repository.activity_lease(plan.generated_model_id, "execution"):
                return self._execute_generated_with_lease(plan)
        except GeneratedModelLifecycleError as exc:
            return self._blocked(plan, exc.code, str(exc))

    def _execute_generated_with_lease(self, plan: SimulationPlan) -> SimulationExecutionResult:
        """Execute while holding the shared deletion/GC exclusion lease."""
        try:
            record = self.generated_model_service.repository.get(plan.generated_model_id)
        except GeneratedModelLifecycleError as exc:
            return self._blocked(plan, exc.code, str(exc))
        if record.get("status") != "enabled" or not record.get("execution_eligible"):
            return self._blocked(plan, "GENERATED_MODEL_NOT_ENABLED", "Generated model is not currently approved and enabled.")
        artifact_id = str(record.get("artifact_id") or "")
        try:
            artifact_path = self.generated_artifact_store.internal_path(artifact_id)
        except KeyError:
            return self._blocked(plan, "GENERATED_MODEL_ARTIFACT_NOT_FOUND", "Generated-model artifact is unavailable.")
        if artifact_path.suffix.casefold() != ".slx":
            return self._blocked(plan, "GENERATED_MODEL_ARTIFACT_NOT_EXECUTABLE", "Generated-model artifact is not a reviewed SLX file.")
        runner = getattr(self.matlab_runtime, "execute_generated_model_artifact", None)
        if not callable(runner):
            return self._blocked(plan, "GENERATED_MODEL_RUNTIME_NOT_AVAILABLE", "MATLAB runtime has no generated-model execution seam.")
        try:
            self.generated_model_service.repository.record_use(plan.generated_model_id, executed=True)
        except GeneratedModelLifecycleError as exc:
            return self._blocked(plan, exc.code, str(exc))
        try:
            raw = runner(
                artifact_path,
                generation_id=plan.generated_model_id,
                model_ir_hash=str(record.get("model_ir_hash") or ""),
                artifact_id=artifact_id,
                model_ir=dict(record.get("model_ir") or {}),
            )
        except Exception as exc:
            self._record_operation(
                "EXECUTE_GENERATED_MODEL",
                plan.generated_model_id,
                status="failed",
                summary={"executed": False, "artifact_id": artifact_id},
                error_code=type(exc).__name__,
            )
            try:
                self.generated_model_service.mark_execution_failed(plan.generated_model_id, reason=type(exc).__name__)
            except GeneratedModelLifecycleError:
                pass
            return self._blocked(plan, "GENERATED_MODEL_EXECUTION_FAILED", type(exc).__name__)
        generated_raw_result = raw.get("generated_result") if isinstance(raw.get("generated_result"), dict) else {}
        generated_raw_outputs = generated_raw_result.get("outputs") if isinstance(generated_raw_result.get("outputs"), list) else []
        self._record_operation(
            "EXECUTE_GENERATED_MODEL",
            plan.generated_model_id,
            status="success" if raw.get("executed") and raw.get("status") == "completed" else "failed",
            summary={
                "executed": bool(raw.get("executed")),
                "solver_status": str(raw.get("status") or "unknown"),
                "artifact_id": artifact_id,
                "model_ir_hash": str(record.get("model_ir_hash") or ""),
                "output_count": len(generated_raw_outputs),
                "duration_seconds": raw.get("duration_seconds"),
            },
            error_code=None if raw.get("executed") and raw.get("status") == "completed" else "GENERATED_MODEL_EXECUTION_INCOMPLETE",
        )
        critique = self.result_critic.critique(raw, record)
        analytical = critique.get("analytical_check") if isinstance(critique.get("analytical_check"), dict) else {}
        self._record_operation(
            "CRITIQUE_GENERATED_RESULT",
            plan.generated_model_id,
            status="success" if critique.get("verdict") != "fail" else "failed",
            summary={
                "verdict": str(critique.get("verdict") or "unknown"),
                "validation_level": str(critique.get("validation_level") or "basic"),
                "checked_output_count": int(critique.get("checked_output_count") or 0),
                "analytical_status": str(analytical.get("status") or "NOT_APPLICABLE"),
                "issue_codes": [
                    str(item.get("code"))
                    for item in (critique.get("issues") or [])
                    if isinstance(item, dict) and item.get("code")
                ][:20],
            },
            error_code="GENERATED_RESULT_CRITIC_FAILED" if critique.get("verdict") == "fail" else None,
        )
        evidence = {
            **dict(raw.get("evidence") or {}),
            "result_critic": critique,
            "analytical_cross_check": dict(critique.get("analytical_check") or {}),
        }
        generated_result = (
            dict(raw.get("generated_result") or {})
            if isinstance(raw.get("generated_result"), dict)
            else {"outputs": dict(raw.get("outputs") or {})}
        )
        if critique["verdict"] == "fail":
            try:
                self.generated_model_service.mark_execution_failed(plan.generated_model_id, reason="result_critic_failed")
            except GeneratedModelLifecycleError:
                pass
            return SimulationExecutionResult(
                plan_id=plan.plan_id,
                executed=False,
                status="failed",
                solver_backend="matlab",
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
                duration_seconds=raw.get("duration_seconds"),
                result=generated_result,
                warnings=["generated_model_result_rejected_by_critic"],
                errors=[dict(item) for item in critique["issues"] if item["severity"] == "error"],
                evidence=evidence,
            )
        warnings = [item["code"] for item in critique["issues"] if item["severity"] == "warning"]
        return SimulationExecutionResult(
            plan_id=plan.plan_id,
            executed=bool(raw.get("executed")),
            status="completed" if critique["verdict"] == "pass" else "completed_with_warnings",
            solver_backend="matlab",
            started_at=raw.get("started_at"),
            finished_at=raw.get("finished_at"),
            duration_seconds=raw.get("duration_seconds"),
            result=generated_result,
            warnings=list(generated_result.get("warnings") or []) + warnings,
            errors=[],
            cfd_executed=False,
            evidence=evidence,
        )

    def _execute_matlab(self, plan: SimulationPlan) -> SimulationExecutionResult:
        normalized = ModelRegistry().normalize_inputs(str(plan.model_id), plan.inputs)
        if not normalized.valid:
            error = normalized.errors[0] if normalized.errors else {"code": "SIMULATION_INPUTS_INCOMPLETE", "message": "Missing inputs: " + ", ".join(normalized.missing_inputs)}
            return self._blocked(plan, error["code"], error["message"])
        request = MatlabExecutionRequest(
            plan_id=plan.plan_id,
            model_id=str(plan.model_id or ""),
            matlab_entrypoint=str(plan.matlab_entrypoint or ""),
            inputs=normalized.canonical_inputs,
            confirmed=True,
        )
        raw = self.matlab_runtime.execute(request)
        return SimulationExecutionResult(
            plan_id=plan.plan_id,
            executed=raw.executed,
            status=raw.status,
            solver_backend="matlab",
            matlab_entrypoint=raw.matlab_entrypoint,
            started_at=raw.started_at,
            finished_at=raw.finished_at,
            duration_seconds=raw.duration_seconds,
            result=dict(raw.result),
            result_files=list(raw.result_files),
            warnings=list(raw.warnings),
            errors=list(raw.errors),
            cfd_executed=False,
            evidence=dict(raw.evidence),
        )

    def _execute_python(self, plan: SimulationPlan) -> SimulationExecutionResult:
        try:
            raw = self.python_runner(str(plan.scenario_id), dict(plan.inputs), model_id=plan.model_id)
        except Exception as exc:
            return self._blocked(plan, "SIMULATION_EXECUTION_ERROR", type(exc).__name__)
        success = bool(raw.get("success"))
        error = raw.get("error")
        return SimulationExecutionResult(
            plan_id=plan.plan_id,
            executed=success,
            status="completed" if success else str(raw.get("status") or "failed"),
            solver_backend="python",
            duration_seconds=(float(raw["duration_ms"]) / 1000) if raw.get("duration_ms") is not None else None,
            result=dict(raw.get("outputs") or {}),
            warnings=list(raw.get("warnings") or []),
            errors=[dict(error)] if isinstance(error, dict) else [],
            cfd_executed=False,
            evidence=dict(raw.get("evidence") or {}),
        )

    @staticmethod
    def _blocked(plan: SimulationPlan, code: str, message: str) -> SimulationExecutionResult:
        return SimulationExecutionResult(
            plan_id=plan.plan_id,
            status="blocked",
            solver_backend=plan.solver_backend,
            matlab_entrypoint=plan.matlab_entrypoint,
            warnings=["simulation_execution_not_completed"],
            errors=[{"code": code, "message": message}],
            cfd_executed=False,
        )

    def _record_operation(
        self,
        action: str,
        generation_id: str,
        *,
        status: str,
        summary: dict[str, Any],
        error_code: str | None = None,
    ) -> None:
        recorder = self.operation_recorder
        record = getattr(recorder, "record", None)
        if not callable(record):
            return
        try:
            record(
                action,
                generation_id,
                status=status,
                summary=summary,
                error_code=error_code,
            )
        except Exception:
            # Operational evidence must not change the solver or safety result.
            return


__all__ = ["ConfirmedSimulationExecutor"]
