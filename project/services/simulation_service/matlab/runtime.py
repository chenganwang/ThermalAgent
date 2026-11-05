from __future__ import annotations

import hashlib
import importlib
import io
import json
import math
import platform
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Callable, Mapping

from ..model_catalog import executable_matlab_dispatcher_ids
from .config import MatlabIntegrationConfig, load_matlab_integration_config
from .discovery import discover_matlab
from .schemas import (
    MatlabConnectionStatus,
    MatlabExecutionRequest,
    MatlabExecutionResult,
    utc_now_iso,
)


MATLAB_DISPATCHER = "thermalagent_dispatch"
DEFAULT_ALLOWED_MODELS = executable_matlab_dispatcher_ids()
PLANE_WALL_INPUTS = frozenset(
    {
        "thickness_m",
        "thermal_conductivity_w_mk",
        "area_m2",
        "delta_temperature_k",
        "hot_temperature_c",
        "cold_temperature_c",
    }
)


class MatlabRuntimeManager:
    """Own one serialized MATLAB Engine session without import-time startup."""

    def __init__(
        self,
        *,
        config: MatlabIntegrationConfig | None = None,
        engine_factory: Callable[..., object] | None = None,
        import_engine: Callable[[], object] | None = None,
        model_dir: str | Path | None = None,
        allowed_models: set[str] | frozenset[str] | None = None,
        execution_mode: str = "real",
    ) -> None:
        self.config = config or load_matlab_integration_config()
        self._engine_factory = engine_factory
        self._import_engine = import_engine
        self.model_dir = Path(model_dir) if model_dir is not None else self.config.project_root / "simulation_models" / "matlab"
        self.allowed_models = frozenset(allowed_models or DEFAULT_ALLOWED_MODELS)
        self.execution_mode = "mock" if execution_mode == "mock" else "real"
        self._lock = RLock()
        self._engine: object | None = None
        self._owned_session = False
        self._runtime_state = "stopped"
        self._matlab_version: str | None = None
        self._dispatcher_callable = False
        self._last_error: dict[str, Any] | None = None
        self._last_check_at: str | None = None

    def connection_status(self, *, start: bool = False) -> MatlabConnectionStatus:
        if start:
            return self.start()
        with self._lock:
            import_ok = self._engine_factory is not None or self._engine_import_status()[0]
            discovery = discover_matlab(self.config)
            connected = bool(
                self._engine is not None
                and self._runtime_state in {"ready", "busy"}
                and self._matlab_version
                and self._dispatcher_callable
            )
            self._last_check_at = utc_now_iso()
            configured = bool(self.config.enabled)
            available = bool(configured and import_ok and discovery.matlab_exe_found)
            return MatlabConnectionStatus(
                configured=configured,
                available=available,
                connected=connected,
                engine_import_ok=import_ok,
                engine_started=self._engine is not None,
                matlab_version=self._matlab_version,
                python_version=platform.python_version(),
                # Host paths are deliberately not exposed through the public contract.
                matlab_root=None,
                engine_error=self._last_error,
                last_check_at=self._last_check_at,
                execution_mode=self.execution_mode if connected else "unavailable",
                uses_real_matlab=bool(connected and self.execution_mode == "real"),
                runtime_state=self._runtime_state,
                matlab_root_detected=bool(discovery.matlab_exe_found),
                dispatcher_callable=self._dispatcher_callable,
                owned_session=self._owned_session,
            )

    def start(self) -> MatlabConnectionStatus:
        with self._lock:
            if self._engine is not None:
                return self.connection_status(start=False)
            blocked = self._startup_block()
            if blocked is not None:
                self._runtime_state = blocked[0]
                self._last_error = {"code": blocked[1], "message": blocked[2]}
                return self.connection_status(start=False)
            self._runtime_state = "starting"
            self._last_error = None
            try:
                self._engine = self._create_engine()
                self._owned_session = True
                self._initialize_engine(self._engine)
                self._runtime_state = "ready"
            except Exception as exc:
                self._safe_close(self._engine)
                self._engine = None
                self._owned_session = False
                self._dispatcher_callable = False
                self._runtime_state = "failed"
                self._last_error = {
                    "code": "MATLAB_START_TIMEOUT" if _is_timeout(exc) else "MATLAB_START_FAILED",
                    "message": type(exc).__name__,
                }
            return self.connection_status(start=False)

    def warmup(self) -> MatlabConnectionStatus:
        return self.start()

    def simulation_build_capabilities(self) -> dict[str, Any]:
        """Run the fixed autonomous-modeling probe on this owned Engine.

        This intentionally exposes no generic Engine callback or function-name
        input. The probe itself contains the complete reviewed query allowlist.
        """

        from ..modeling.capabilities import SimulationBuildCapabilityProbe

        with self._lock:
            status = self.start()
            if not status.connected or self._engine is None:
                code = str((status.engine_error or {}).get("code") or "MATLAB_NOT_READY")
                return {
                    "probe_version": SimulationBuildCapabilityProbe.probe_version,
                    "matlab": {"available": False, "version": status.matlab_version},
                    "simulink": {"installed": False, "licensed": False, "available": False},
                    "simscape": {"installed": False, "licensed": False, "available": False},
                    "simscape_fluids": {"installed": False, "licensed": False, "available": False},
                    "domains": {
                        "thermal": {"available": False, "status": "CAPABILITY_NOT_AVAILABLE"},
                        "isothermal_liquid": {"available": False, "status": "CAPABILITY_NOT_AVAILABLE"},
                    },
                    "installed_products": [],
                    "approved_blocks": {},
                    "status": "CAPABILITY_NOT_AVAILABLE",
                    "error": {"code": code, "message": "MATLAB Engine is not ready."},
                    "security": {
                        "fixed_queries_only": True,
                        "accepts_user_code": False,
                        "accepts_user_paths": False,
                        "executes_simulation": False,
                    },
                }
            return SimulationBuildCapabilityProbe().probe(self._engine)

    def compile_generated_model(self, plan: object, target_path: Path) -> None:
        """Execute one sealed compiler plan inside the owned serialized Engine.

        No generic callback or function name is exposed. The target must be the
        canonical generated-model staging directory owned by this project.
        """

        from ..modeling.compiler import CompilationError, CompilationPlan
        from ..modeling.simulink_compiler import execute_reviewed_compilation_plan

        if not isinstance(plan, CompilationPlan) or not plan.authentic:
            raise CompilationError("UNAUTHENTICATED_PLAN", "Compilation plan is not planner-issued.")
        target = Path(target_path).resolve()
        staging_root = (self.config.project_root / "runtime" / "generated_models" / "staging").resolve()
        if target.suffix.casefold() != ".slx" or not target.is_relative_to(staging_root):
            raise CompilationError("ARTIFACT_PATH_NOT_ALLOWED", "Generated model target is outside controlled staging.")

        with self._lock:
            status = self.start()
            if not status.connected or self._engine is None:
                code = str((status.engine_error or {}).get("code") or "MATLAB_NOT_READY")
                raise CompilationError(code, "MATLAB Engine is not ready for model compilation.")
            self._runtime_state = "busy"
            try:
                execute_reviewed_compilation_plan(self._engine, plan, target)
            except CompilationError:
                self._runtime_state = "degraded"
                raise
            except Exception as exc:
                self._runtime_state = "degraded"
                raise CompilationError("MATLAB_MODEL_BUILD_FAILED", type(exc).__name__) from exc
            self._runtime_state = "ready"

    def verify_generated_model(self, plan: object, target_path: Path) -> None:
        """Reload the promoted final SLX using the same owned Engine."""

        from ..modeling.compiler import CompilationError, CompilationPlan

        if not isinstance(plan, CompilationPlan) or not plan.authentic:
            raise CompilationError("UNAUTHENTICATED_PLAN", "Compilation plan is not planner-issued.")
        target = Path(target_path).resolve()
        staging_root = (self.config.project_root / "runtime" / "generated_models" / "staging").resolve()
        if target.suffix.casefold() != ".slx" or not target.is_relative_to(staging_root) or "_part" in target.stem:
            raise CompilationError("ARTIFACT_PATH_NOT_ALLOWED", "Final generated model is outside controlled staging.")
        with self._lock:
            status = self.start()
            if not status.connected or self._engine is None:
                code = str((status.engine_error or {}).get("code") or "MATLAB_NOT_READY")
                raise CompilationError(code, "MATLAB Engine is not ready for artifact verification.")
            handle = None
            try:
                handle = self._engine.load_system(str(target), nargout=1)
            except Exception as exc:
                raise CompilationError("GENERATED_ARTIFACT_RELOAD_FAILED", type(exc).__name__) from exc
            finally:
                if handle is not None:
                    try:
                        self._engine.close_system(handle, 0, nargout=0)
                    except Exception:
                        pass

    def execute_generated_model_artifact(
        self,
        target_path: Path,
        *,
        generation_id: str,
        model_ir_hash: str,
        artifact_id: str,
        model_ir: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one approved generated SLX through a fixed, no-expression seam."""

        import re

        from ..modeling.model_ir import ModelIR
        from ..modeling.registry import ComponentRegistry
        from ..modeling.result_extraction import GeneratedResultExtractor
        from ..modeling.validator import ModelValidator

        safe_generation = re.fullmatch(r"gen_[a-f0-9]{32}", str(generation_id or ""))
        safe_hash = re.fullmatch(r"[a-f0-9]{64}", str(model_ir_hash or ""))
        safe_artifact = re.fullmatch(r"gm_[a-f0-9]{16}_[a-f0-9]{12}", str(artifact_id or ""))
        target = Path(target_path).resolve()
        staging_root = (self.config.project_root / "runtime" / "generated_models" / "staging").resolve()
        if (
            not safe_generation or not safe_hash or not safe_artifact
            or target != (staging_root / f"{artifact_id}.slx").resolve()
            or not target.is_file()
        ):
            raise ValueError("generated model execution identity or artifact is invalid")
        parsed_model_ir = ModelIR.from_dict(model_ir)
        validated = ModelValidator(ComponentRegistry.default()).validate_for_compilation(parsed_model_ir)
        if validated.model_ir_hash != model_ir_hash:
            raise ValueError("generated model output contract does not match the reviewed IR")
        with self._lock:
            status = self.start()
            if not status.connected or self._engine is None:
                code = str((status.engine_error or {}).get("code") or "MATLAB_NOT_READY")
                raise RuntimeError(code)
            started_at = utc_now_iso()
            started = perf_counter()
            handle = None
            self._runtime_state = "busy"
            try:
                handle = self._engine.load_system(str(target), nargout=1)
                model_name = str(self._engine.get_param(handle, "Name", nargout=1))
                raw_simulation = self._run_generated_simulation(
                    self._engine, model_name, self.config.max_runtime_seconds,
                )
            except Exception:
                self._runtime_state = "degraded"
                raise
            finally:
                if handle is not None:
                    try:
                        self._engine.close_system(handle, 0, nargout=0)
                    except Exception:
                        pass
            finished_at = utc_now_iso()
            duration = perf_counter() - started
            logged_values = self._read_generated_output_values(
                self._engine, raw_simulation, parsed_model_ir,
            )
            generated_result = GeneratedResultExtractor().extract(
                logged_values,
                model_ir=parsed_model_ir,
                artifact_id=artifact_id,
                duration_seconds=duration,
            ).to_dict()
            self._runtime_state = "ready"
            return {
                "executed": True,
                "status": "completed",
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": duration,
                "generated_result": generated_result,
                "outputs": generated_result["outputs"],
                "evidence": {
                    "generation_id": generation_id,
                    "model_ir_hash": model_ir_hash,
                    "artifact_id": artifact_id,
                    "solver": "matlab_simulink_simscape",
                    "engine_release": self._matlab_version,
                    "uses_real_matlab": self.execution_mode == "real",
                    "simulation_executed": True,
                },
            }

    @staticmethod
    def _run_generated_simulation(engine: object, model_name: str, timeout_seconds: int) -> object:
        try:
            value = engine.sim(model_name, nargout=1, background=True)
        except TypeError:
            value = engine.sim(model_name, nargout=1)
        if hasattr(value, "result") and callable(value.result):
            try:
                return value.result(timeout=max(int(timeout_seconds), 1))
            except Exception:
                cancel = getattr(value, "cancel", None)
                if callable(cancel):
                    cancel()
                raise
        return value

    @staticmethod
    def _read_generated_output_values(engine: object, simulation_output: object, model_ir: object) -> dict[str, Any]:
        """Read only hash-derived logger names from one SimulationOutput."""

        from ..modeling.compiler import output_logger_name
        from ..modeling.model_ir import ModelIR

        if not isinstance(model_ir, ModelIR):
            raise TypeError("generated output extraction requires parsed Model IR")
        expected_names = [
            output_logger_name(model_ir.digest(), item.id, item.type)
            for item in model_ir.requested_outputs
        ]
        if isinstance(simulation_output, Mapping):
            return {
                name: simulation_output[name]
                for name in expected_names
                if name in simulation_output
            }
        getter = getattr(engine, "get", None)
        if not callable(getter):
            return {}
        values: dict[str, Any] = {}
        for name in expected_names:
            try:
                values[name] = getter(simulation_output, name, nargout=1)
            except Exception:
                continue
        return values

    def execute(self, request: MatlabExecutionRequest) -> MatlabExecutionResult:
        if not request.confirmed:
            return self._failure(request, "SIMULATION_PLAN_NOT_CONFIRMED", "Simulation plan is not confirmed.")
        if request.matlab_entrypoint != MATLAB_DISPATCHER or request.model_id not in self.allowed_models:
            return self._failure(request, "MATLAB_MODEL_NOT_FOUND", "MATLAB model or entrypoint is not allow-listed.")
        invalid_reason = _validate_inputs(request.model_id, request.inputs)
        if invalid_reason is not None:
            return self._failure(request, "MATLAB_REQUEST_INVALID", invalid_reason)

        with self._lock:
            status = self.start()
            if not status.connected or self._engine is None:
                code = str((status.engine_error or {}).get("code") or "MATLAB_NOT_READY")
                return self._failure(request, code, "MATLAB Engine is not ready.")

            started_at = utc_now_iso()
            started = perf_counter()
            stdout = io.StringIO()
            stderr = io.StringIO()
            self._runtime_state = "busy"
            try:
                payload = json.dumps(request.inputs, ensure_ascii=False, sort_keys=True)
                raw = self._dispatch(
                    self._engine,
                    request.model_id,
                    payload,
                    request.timeout_seconds,
                    stdout,
                    stderr,
                )
                parsed = json.loads(str(raw))
                if not isinstance(parsed, dict):
                    raise ValueError("MATLAB dispatcher response must be a JSON object")
                finished_at = utc_now_iso()
                duration = perf_counter() - started
                evidence = {
                    "execution_id": request.execution_id,
                    "plan_id": request.plan_id,
                    "solver": "matlab",
                    # The executor forwards evidence into Agent metadata. Keep
                    # real/mock provenance with this execution, not just status.
                    "execution_mode": self.execution_mode,
                    "uses_real_matlab": self.execution_mode == "real",
                    "is_mock": self.execution_mode == "mock",
                    "cfd_executed": False,
                    "engine_release": self._matlab_version,
                    "model_id": request.model_id,
                    "model_version": "1.0.0",
                    "input_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    "source_hashes": {
                        name: hashlib.sha256((self.model_dir / name).read_bytes()).hexdigest()
                        for name in (f"{MATLAB_DISPATCHER}.m", f"{request.model_id}.m")
                        if (self.model_dir / name).is_file()
                    },
                    "normalized_inputs": dict(request.inputs),
                    "outputs": dict(parsed),
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_ms": int(duration * 1000),
                    "stdout": _bounded(stdout.getvalue()),
                    "stderr": _bounded(stderr.getvalue()),
                    "status": "SUCCEEDED",
                }
                self._runtime_state = "ready"
                return MatlabExecutionResult(
                    executed=True,
                    status="completed",
                    plan_id=request.plan_id,
                    model_id=request.model_id,
                    matlab_entrypoint=request.matlab_entrypoint,
                    execution_id=request.execution_id,
                    execution_mode=self.execution_mode,
                    uses_real_matlab=self.execution_mode == "real",
                    matlab_version=self._matlab_version,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=duration,
                    result=dict(parsed),
                    stdout=_bounded(stdout.getvalue()),
                    stderr=_bounded(stderr.getvalue()),
                    evidence=evidence,
                )
            except Exception as exc:
                self._runtime_state = "degraded"
                code = "MATLAB_TIMEOUT" if _is_timeout(exc) else "MATLAB_EXECUTION_ERROR"
                return self._failure(
                    request,
                    code,
                    type(exc).__name__,
                    started_at=started_at,
                    duration_seconds=perf_counter() - started,
                    stdout=stdout.getvalue(),
                    stderr=stderr.getvalue(),
                )

    def shutdown(self) -> None:
        with self._lock:
            engine = self._engine
            self._runtime_state = "stopping" if engine is not None else "stopped"
            self._engine = None
            self._dispatcher_callable = False
            self._matlab_version = None
            self._safe_close(engine)
            self._owned_session = False
            self._runtime_state = "stopped"

    close = shutdown

    def _startup_block(self) -> tuple[str, str, str] | None:
        if not self.config.enabled:
            return "disabled", "MATLAB_DISABLED", "MATLAB integration is disabled."
        if not self.config.allow_engine_start:
            return "stopped", "MATLAB_START_NOT_ALLOWED", "MATLAB Engine startup is disabled."
        if not self.config.allow_api:
            return "stopped", "MATLAB_API_DISABLED", "MATLAB API execution is disabled."
        if self.config.require_license_confirmation and not self.config.operator_confirmed_license:
            return "stopped", "MATLAB_LICENSE_NOT_CONFIRMED", "Operator license confirmation is required."
        import_ok, _ = self._engine_import_status()
        if self._engine_factory is None and not import_ok:
            return "not_importable", "MATLAB_ENGINE_IMPORT_FAILED", "MATLAB Engine for Python is unavailable."
        return None

    def _engine_import_status(self) -> tuple[bool, object | None]:
        try:
            module = self._import_engine() if self._import_engine is not None else importlib.import_module("matlab.engine")
        except Exception:
            return False, None
        return True, module

    def _create_engine(self) -> object:
        if self._engine_factory is not None:
            try:
                return self._engine_factory(timeout_seconds=self.config.engine_timeout_seconds)
            except TypeError:
                return self._engine_factory()
        ok, module = self._engine_import_status()
        if not ok or module is None:
            raise ImportError("matlab.engine")
        starter = getattr(module, "start_matlab")
        try:
            value = starter(background=True)
        except TypeError:
            return starter()
        if hasattr(value, "result") and callable(value.result):
            try:
                return value.result(timeout=max(int(self.config.engine_timeout_seconds), 1))
            except Exception:
                cancel = getattr(value, "cancel", None)
                if callable(cancel):
                    cancel()
                raise
        return value

    def _initialize_engine(self, engine: object) -> None:
        addpath = getattr(engine, "addpath")
        addpath(str(self.model_dir), nargout=0)
        version = getattr(engine, "version")
        try:
            release = version("-release", nargout=1)
        except TypeError:
            release = version("-release")
        self._matlab_version = str(release)
        which = getattr(engine, "which")
        try:
            dispatcher = which(MATLAB_DISPATCHER, nargout=1)
        except TypeError:
            dispatcher = which(MATLAB_DISPATCHER)
        self._dispatcher_callable = bool(str(dispatcher or "").strip())
        if not self._dispatcher_callable:
            raise RuntimeError("MATLAB dispatcher is not callable")

    @staticmethod
    def _dispatch(
        engine: object,
        model_id: str,
        request_json: str,
        timeout_seconds: int,
        stdout: io.StringIO,
        stderr: io.StringIO,
    ) -> object:
        dispatcher = getattr(engine, MATLAB_DISPATCHER)
        kwargs = {"nargout": 1, "stdout": stdout, "stderr": stderr, "background": True}
        try:
            value = dispatcher(model_id, request_json, **kwargs)
        except TypeError:
            kwargs.pop("background", None)
            value = dispatcher(model_id, request_json, **kwargs)
        if hasattr(value, "result") and callable(value.result):
            try:
                return value.result(timeout=max(int(timeout_seconds), 1))
            except Exception:
                cancel = getattr(value, "cancel", None)
                if callable(cancel):
                    cancel()
                raise
        return value

    def _failure(
        self,
        request: MatlabExecutionRequest,
        code: str,
        message: str,
        *,
        started_at: str | None = None,
        duration_seconds: float | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> MatlabExecutionResult:
        return MatlabExecutionResult(
            executed=False,
            status="failed",
            plan_id=request.plan_id,
            model_id=request.model_id,
            matlab_entrypoint=request.matlab_entrypoint,
            execution_id=request.execution_id,
            execution_mode="unavailable" if self._engine is None else self.execution_mode,
            uses_real_matlab=False,
            matlab_version=self._matlab_version,
            started_at=started_at,
            finished_at=utc_now_iso() if started_at else None,
            duration_seconds=duration_seconds,
            stdout=_bounded(stdout),
            stderr=_bounded(stderr),
            warnings=["matlab_execution_not_completed"],
            errors=[{"code": code, "message": message}],
            cfd_executed=False,
        )

    @staticmethod
    def _safe_close(engine: object | None) -> None:
        if engine is None:
            return
        for name in ("quit", "exit", "close"):
            method = getattr(engine, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                return


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


def _validate_inputs(model_id: str, inputs: dict[str, Any]) -> str | None:
    if model_id != "plane_wall_steady_v1":
        return "Unsupported MATLAB model input contract."
    # Resolve only the built-in contract; operator metadata cannot expand this
    # boundary. Defer the catalog import so Engine/module initialization is unchanged.
    from ..catalog.model_registry import ModelRegistry

    catalog_path = Path(__file__).resolve().parents[1] / "catalog" / "data" / "models.json"
    normalized = ModelRegistry(data_path=catalog_path).normalize_inputs(model_id, inputs)
    if normalized.errors:
        error = normalized.errors[0]
        # Keep the Runtime error envelope while retaining the shared conflict/invalid
        # code. Normalization derives abs(hot-cold) without mutating the request.
        return f"{error['code']}: {error.get('field', 'inputs')}: {error.get('message', 'Invalid model input.')}"
    if normalized.missing_inputs:
        return "SIMULATION_INPUTS_INCOMPLETE: " + ", ".join(normalized.missing_inputs)
    return None


def _bounded(value: str, limit: int = 4000) -> str:
    return str(value or "")[:limit]


_DEFAULT_RUNTIME: MatlabRuntimeManager | None = None


def get_matlab_runtime_manager() -> MatlabRuntimeManager:
    global _DEFAULT_RUNTIME
    if _DEFAULT_RUNTIME is None:
        _DEFAULT_RUNTIME = MatlabRuntimeManager()
    return _DEFAULT_RUNTIME


def reset_matlab_runtime_manager() -> None:
    global _DEFAULT_RUNTIME
    if _DEFAULT_RUNTIME is not None:
        _DEFAULT_RUNTIME.shutdown()
    _DEFAULT_RUNTIME = None


__all__ = [
    "DEFAULT_ALLOWED_MODELS",
    "MATLAB_DISPATCHER",
    "PLANE_WALL_INPUTS",
    "MatlabRuntimeManager",
    "get_matlab_runtime_manager",
    "reset_matlab_runtime_manager",
]
