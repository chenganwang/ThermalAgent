"""Replaceable CFD execution adapters. Only FluentRunner owns solver processes."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable, Protocol, runtime_checkable

from services.physics_service.contracts import PhysicsQuantity, PhysicsValidationRequest
from services.physics_service.validator import validate_physics

from .config import FluentConfig
from .contracts import CaseSpec, FluentError
from .results import parse_results


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_journal(case: CaseSpec, iterations: int) -> str:
    if case.backend != "fluent":
        raise ValueError("Mock cases do not have Fluent journals")
    commands = ['/file/set-tui-version "24.2"', "/file/start-transcript solver.trn", "/file/set-error-on-invalid-command yes"]
    commands.append('/file/read-case-data "input.cas.h5"' if case.data_file else '/file/read-case "input.cas.h5"')
    if case.initialize:
        commands.append("/solve/initialize/hyb-initialization")
    commands += [f"/solve/iterate {iterations}", '/file/write-case-data "output.cas.h5"', "/file/stop-transcript", "/exit yes"]
    return "\n".join(commands) + "\n"


@dataclass(frozen=True)
class RunnerContext:
    folder: Path
    case: CaseSpec
    executable: Path | None
    iterations: int
    processors: int
    timeout_seconds: int


@dataclass
class RunnerOutcome:
    status: str
    result: dict | None = None
    error: dict | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    exit_code: int | None = None
    diagnostics: dict = field(default_factory=dict)
    fallback_eligible: bool = False


@runtime_checkable
class CFDRunner(Protocol):
    """Inject fixed implementations in application code, never from HTTP input."""

    backend: str
    version: str

    def prepare(self, folder: Path, case: CaseSpec, config: FluentConfig, iterations: int) -> dict[str, str]: ...

    def execute(self, context: RunnerContext, on_started: Callable[[dict], None]) -> RunnerOutcome: ...


class FluentRunner:
    backend = "fluent"
    version = "fluent-24.2-steady-v1"

    def __init__(self, *, process_factory=None):
        self._popen = process_factory or subprocess.Popen

    def prepare(self, folder: Path, case: CaseSpec, config: FluentConfig, iterations: int) -> dict[str, str]:
        assets = {"input.cas.h5": config.asset(case.case_file)}
        if case.data_file:
            assets["input.dat.h5"] = config.asset(case.data_file)
        for name, source in assets.items():
            shutil.copyfile(source, folder / name)
        (folder / "run.jou").write_text(render_journal(case, iterations), encoding="utf-8")
        return {name: sha256_file(folder / name) for name in [*assets, "run.jou"]}

    @staticmethod
    def terminate(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20,
                                    creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            if result.returncode and process.poll() is None:
                raise RuntimeError("Process tree termination failed")
        else:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=20)

    @staticmethod
    def _scan_log(path: Path) -> tuple[bytes, bool, bool, bool, bool]:
        """Bounded tail plus whole-stream error flags; numerical failure is never fallback."""
        tail = b""
        environment_error = solver_error = numerical_progress = numerical_failure = False
        if not path.is_file():
            return tail, environment_error, solver_error, numerical_progress, numerical_failure
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                combined = tail[-256:] + chunk
                environment_error |= bool(re.search(rb"license checkout failed|unable to (?:obtain|check.?out).*license|licensing error|MPI_Init.*(?:failed|error)|unable to (?:start|spawn).*(?:fluent|cortex|mpi)", combined, re.I))
                solver_error |= bool(re.search(rb"(?:^|[\r\n])\s*Error:|floating point exception|divergence detected|fatal error", combined, re.I))
                numerical_failure |= bool(re.search(rb"floating point exception|divergence detected|fatal error", combined, re.I))
                numerical_progress |= bool(re.search(rb"(?:^|[\r\n])\s*[1-9]\d*\s+[-+]?\d+(?:\.\d+)?[eEdD][-+]?\d+", combined))
                tail = (tail + chunk)[-8 * 1024 * 1024:]
        return tail, environment_error, solver_error, numerical_progress, numerical_failure

    def execute(self, context: RunnerContext, on_started: Callable[[dict], None]) -> RunnerOutcome:
        process = None
        code = None
        try:
            argv = [str(context.executable), context.case.dimension, "-g", "-wait", f"-t{context.processors}", "-i", "run.jou"]
            flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            with (context.folder / "launcher.log").open("wb") as log:
                try:
                    process = self._popen(argv, cwd=str(context.folder), stdin=subprocess.DEVNULL, stdout=log,
                                          stderr=subprocess.STDOUT, shell=False, **flags)
                except OSError:
                    return RunnerOutcome("failed", error={"code": "FLUENT_START_FAILED", "message": "The local Fluent process could not start."},
                                         diagnostics={"category": "environment", "solver_started": False}, fallback_eligible=True)
                on_started({"pid": process.pid})
                code = process.wait(timeout=context.timeout_seconds)
            transcript = context.folder / "solver.trn"
            tail, environment_error, solver_error, progress, numerical_failure = self._scan_log(transcript)
            _, launcher_environment_error, launcher_solver_error, launcher_progress, launcher_numerical_failure = self._scan_log(context.folder / "launcher.log")
            environment_error |= launcher_environment_error
            solver_error |= launcher_solver_error
            progress |= launcher_progress
            numerical_failure |= launcher_numerical_failure
            # Even a license error must not mask an already-running numerical failure.
            has_output = any((context.folder / name).is_file() for name in ("output.cas.h5", "output.dat.h5"))
            # Require a positive environment signal; an exit code alone is ambiguous.
            startup_failure = environment_error and not progress and not has_output and not numerical_failure
            if startup_failure:
                return RunnerOutcome("failed", error={"code": "FLUENT_PROCESS_FAILED", "message": "Fluent startup or license availability prevented execution."},
                                     exit_code=code, diagnostics={"category": "environment", "solver_started": False}, fallback_eligible=True)
            if code != 0:
                raise FluentError("FLUENT_PROCESS_FAILED", "Fluent exited with a nonzero status. Review the local solver log.")
            if not transcript.is_file():
                raise FluentError("FLUENT_EVIDENCE_MISSING", "Fluent did not produce its required transcript.")
            if solver_error or environment_error:
                raise FluentError("FLUENT_SOLVER_ERROR", "The Fluent transcript reports a solver or command error.")
            for name in ("output.cas.h5", "output.dat.h5"):
                output = context.folder / name
                if not output.is_file() or not output.stat().st_size or output.is_symlink() or output.resolve().parent != context.folder.resolve():
                    raise FluentError("FLUENT_OUTPUT_MISSING", "Fluent did not produce both required result files.")
            result = parse_results(context.folder, context.case, tail.decode("utf-8", errors="replace"))
            result.update(effective_backend="fluent", is_mock=False, cfd_executed=True, solver_executed=True)
            return RunnerOutcome("completed", result=result, exit_code=code,
                                 outputs={name: sha256_file(context.folder / name) for name in ("output.cas.h5", "output.dat.h5", "solver.trn")},
                                 diagnostics={"category": "execution", "solver_started": True})
        except subprocess.TimeoutExpired:
            try:
                self.terminate(process)
                return RunnerOutcome("timed_out", error={"code": "FLUENT_TIMEOUT", "message": "Fluent exceeded the time limit; its owned process tree was stopped."})
            except Exception:
                return RunnerOutcome("interrupted", error={"code": "FLUENT_TERMINATION_FAILED", "message": "Could not confirm solver termination. Local reconciliation is required."})
        except Exception as exc:
            status = "failed"
            if process is not None and process.poll() is None:
                try:
                    self.terminate(process)
                except Exception:
                    status = "interrupted"
            return RunnerOutcome(status, exit_code=code, error=exc.public() if isinstance(exc, FluentError) else
                                 {"code": "FLUENT_WORKER_FAILED", "message": "The Fluent runner failed. Review local evidence."})


class MockCFDRunner:
    backend = "mock"
    version = "mock-plane-wall-v1"

    def prepare(self, folder: Path, case: CaseSpec, config: FluentConfig, iterations: int) -> dict[str, str]:
        if case.backend != "mock" or case.demo_inputs is None:
            raise FluentError("CFD_MOCK_CASE_INVALID", "Mock execution requires a declared demo case.")
        payload = {"schema_version": "1.0", "backend": "mock", "is_mock": True, "runner_version": self.version,
                   "case_id": case.case_id, "parameters": case.demo_inputs.model_dump(),
                   "formula": "Q = k*A*(T_hot-T_cold)/L; T(x)=T_hot+(T_cold-T_hot)*x/L",
                   "curve_axis": "position_m", "sample_count": 21}
        path = folder / "mock_input.json"
        path.write_bytes(canonical_json(payload))
        return {path.name: sha256_file(path)}

    def execute(self, context: RunnerContext, on_started: Callable[[dict], None]) -> RunnerOutcome:
        try:
            payload = json.loads((context.folder / "mock_input.json").read_text(encoding="utf-8"))
            parameters = context.case.demo_inputs.model_dump()
            if payload["parameters"] != parameters or payload["runner_version"] != self.version:
                raise ValueError("Prepared demo parameters changed")
            p = context.case.demo_inputs
            heat = p.conductivity_w_mk * p.area_m2 * (p.hot_temperature_k - p.cold_temperature_k) / p.thickness_m
            points = [[p.thickness_m * i / 20, p.hot_temperature_k + (p.cold_temperature_k - p.hot_temperature_k) * i / 20] for i in range(21)]
            if not math.isfinite(heat) or not all(math.isfinite(v) for row in points for v in row):
                raise ValueError("Mock numerical overflow")
            physical = validate_physics(PhysicsValidationRequest(quantities=[
                PhysicsQuantity(name="heat_rate", value=heat, unit="W"),
                PhysicsQuantity(name="cold_temperature", value=p.cold_temperature_k, unit="K", quantity_type="absolute_temperature"),
                PhysicsQuantity(name="hot_temperature", value=p.hot_temperature_k, unit="K", quantity_type="absolute_temperature"),
            ]))
            result = {"metrics": [{"name": "demo_heat_rate", "value": heat, "unit": "W"},
                                   {"name": "demo_cold_temperature", "value": p.cold_temperature_k, "unit": "K"}],
                      "histories": [{"name": "demo_temperature_profile", "unit": "K", "axis": "position_m", "axis_unit": "m", "points": points}],
                      "validation": {"status": physical.status, "validator_version": physical.validator_version,
                                     "checks": [{"name": "demo_arithmetic", "status": physical.status, "message": "Only declared demo arithmetic and absolute-temperature bounds were checked."}]},
                      "is_mock": True, "effective_backend": "mock", "cfd_executed": False, "solver_executed": False,
                      "demo_parameters": parameters, "formula": payload["formula"], "report_artifacts": [],
                      "limitations": ["MOCK DEMO ONLY: deterministic plane-wall arithmetic, not a CFD solution.",
                                      "These demo parameters do not represent the originally requested real case.",
                                      "This output cannot validate a real engineering design, mesh, turbulence model, or solver convergence."]}
            path = context.folder / "mock_result.json"
            path.write_bytes(canonical_json(result))
            digest = sha256_file(path)
            result["report_artifacts"] = [{"name": "mock_demo", "artifact_id": "mock_result", "sha256": digest, "size_bytes": path.stat().st_size}]
            return RunnerOutcome("completed", result=result, outputs={path.name: digest}, diagnostics={"category": "demo", "solver_started": False})
        except (OSError, ValueError, KeyError, OverflowError):
            return RunnerOutcome("failed", error={"code": "CFD_MOCK_FAILED", "message": "The declared mock demo could not be evaluated."})


__all__ = ["CFDRunner", "FluentRunner", "MockCFDRunner", "RunnerContext", "RunnerOutcome", "render_journal"]
