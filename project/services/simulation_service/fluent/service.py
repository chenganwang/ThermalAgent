"""Persisted CFD jobs with pluggable runners and explicit, reproducible mock fallback."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock, Thread
from uuid import uuid4

from .config import FluentConfig
from .contracts import CaseSpec, FluentError, PrepareJob, RunJob, builtin_mock_case
from .results import build_report
from .runners import CFDRunner, FluentRunner, MockCFDRunner, RunnerContext, RunnerOutcome, canonical_json as _canonical, sha256_file as _sha, render_journal

JOB_ID = re.compile(r"^fluent_[a-f0-9]{32}$")
PUBLIC_KEYS = ("job_id", "status", "case_id", "iterations", "processors", "created_at", "updated_at",
               "input_fingerprint", "steps", "result", "error", "is_mock", "requested_backend", "effective_backend",
               "fallback_reason", "requested_case_id", "effective_case_id", "attempts")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fallback_reason(code: str | None) -> dict | None:
    if code is None:
        return None
    messages = {
        "FLUENT_DISABLED": "The Fluent backend is disabled; a declared mock demo is available.",
        "FLUENT_EXECUTION_DISABLED": "Real Fluent execution is disabled; a declared mock demo is available.",
        "FLUENT_SOLVER_NOT_FOUND": "A usable local Fluent installation was not found.",
        "FLUENT_NO_REGISTERED_CASES": "No executable Fluent case is registered.",
        "FLUENT_REGISTRY_INVALID": "The Fluent case registry or its assets require review.",
    }
    return {"code": code, "message": messages.get(code, "The real CFD backend is unavailable.")}


@contextmanager
def _exclusive(path: Path):
    """Non-blocking OS lock shared across service instances and both backends."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            raise FluentError("FLUENT_BUSY", "Another CFD operation owns this worker. Retry later.", 409) from None
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _case_snapshot(case: CaseSpec) -> dict:
    payload = case.model_dump()
    if case.backend == "fluent":
        payload.update(case_file="input.cas.h5", data_file="input.dat.h5" if case.data_file else None)
    return payload


class FluentService:
    """Backward-compatible service name; runners own all execution specifics.

    Auto fallback is limited to a fingerprinted demo and environment failures.
    Case revocation, changed inputs, numerical errors, and uncertain termination
    cannot be bypassed by mock execution.
    """

    def __init__(self, config: FluentConfig | None = None, *, process_factory=None,
                 runners: dict[str, CFDRunner] | None = None, runner: CFDRunner | None = None, environment_detector=None):
        self.config = config or FluentConfig.from_env()
        self.runners: dict[str, CFDRunner] = {"fluent": FluentRunner(process_factory=process_factory), "mock": MockCFDRunner()}
        if runners:
            self.runners.update(runners)
        if runner:
            self.runners[runner.backend] = runner
        if any(name not in {"fluent", "mock"} or candidate.backend != name or not isinstance(candidate, CFDRunner)
               for name, candidate in self.runners.items()):
            raise FluentError("CFD_RUNNER_INVALID", "Register a compatible fixed CFD runner.", 503)
        if environment_detector is None:
            from .environment import detect_environment
            environment_detector = detect_environment
        self._detect = environment_detector
        self._lock = RLock()
        self._threads: dict[str, Thread] = {}

    def _inventory(self):
        if self.config.mode == "mock":
            environment = {"available": False, "executable": None, "report": {
                "schema_version": "1.0", "status": "deferred", "solver_found": False,
                "version": None, "license_checked": False, "requested_path_kind": "not_checked",
                "resolution_source": "deferred", "checks": [{"name": "integration", "status": "not_checked",
                    "code": "FLUENT_INTEGRATION_DEFERRED",
                    "message": "Real Fluent integration is deferred. Mock mode does not inspect the installation or license."}],
            }}
        else:
            environment = self._detect(self.config.executable)
        warnings = []
        try:
            cases = self.config.cases()
        except FluentError as exc:
            cases = {}
            warnings.append(exc.code)
        real_cases = {key: case for key, case in cases.items() if case.backend == "fluent"}
        reason = ("FLUENT_DISABLED" if not self.config.enabled else
                  "FLUENT_EXECUTION_DISABLED" if not self.config.execution_enabled else
                  "FLUENT_SOLVER_NOT_FOUND" if not environment["available"] else
                  warnings[0] if warnings else "FLUENT_NO_REGISTERED_CASES" if not real_cases else None)
        if self.config.mode == "mock":
            reason = None
        if reason and reason not in warnings:
            warnings.append(reason)
        if self.config.mock_enabled:
            cases["mock_cfd_demo"] = builtin_mock_case()
        selected = "mock" if self.config.mode == "mock" or (self.config.mode == "auto" and reason and self.config.mock_enabled) else "fluent"
        if self.config.mode == "fluent":
            visible = real_cases
        elif selected == "mock":
            visible = {key: case for key, case in cases.items() if case.backend == "mock"}
        else:
            visible = cases
        if not self.config.cfd_enabled:
            warnings.append("CFD_DISABLED")
        if selected == "mock" and not self.config.mock_enabled:
            warnings.append("CFD_MOCK_DISABLED")
        return environment, cases, visible, selected, reason, warnings

    def status(self) -> dict:
        environment, _, visible, selected, reason, warnings = self._inventory()
        executable = self.config.cfd_enabled and (self.config.mock_enabled if selected == "mock" else reason is None)
        return {"schema_version": "1.0", "enabled": self.config.cfd_enabled, "fluent_enabled": self.config.enabled,
                "execution_enabled": executable, "real_execution_enabled": self.config.execution_enabled,
                "mock_enabled": self.config.mock_enabled, "mode": self.config.mode, "requested_backend": self.config.mode,
                "selected_backend": selected, "effective_backend": selected, "is_mock": selected == "mock",
                "fallback_reason": _fallback_reason(reason) if self.config.mode == "auto" and selected == "mock" else None,
                "environment": environment["report"], "solver_found": environment["report"]["solver_found"], "license_checked": False,
                "cases": [{"case_id": case.case_id, "title": case.title, "dimension": case.dimension, "backend": case.backend,
                           "is_mock": case.backend == "mock", "reports": [{"name": r.name, "unit": r.unit} for r in case.reports],
                           "warnings": ["MOCK_DEMO_ONLY"] if case.backend == "mock" else []} for case in visible.values()],
                "warnings": warnings, "limits": {"max_iterations": self.config.max_iterations,
                "max_processors": self.config.max_processors, "timeout_seconds": self.config.timeout_seconds}}

    def _enabled(self):
        if not self.config.cfd_enabled:
            raise FluentError("CFD_DISABLED", "CFD job preparation and execution are disabled.", 403)
        if self.config.mode == "fluent" and not self.config.enabled:
            raise FluentError("FLUENT_DISABLED", "The Fluent backend is disabled.", 403)
        if self.config.mode == "mock" and not self.config.mock_enabled:
            raise FluentError("CFD_MOCK_DISABLED", "Mock CFD execution is disabled.", 403)

    def _folder(self, job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id):
            raise FluentError("FLUENT_JOB_NOT_FOUND", "CFD job was not found.", 404)
        folder = self.config.jobs_root / job_id
        if folder.is_symlink() or folder.resolve().parent != self.config.jobs_root.resolve():
            raise FluentError("FLUENT_JOB_INVALID", "The job location is invalid.", 409)
        return folder

    def _read(self, job_id: str) -> dict:
        path = self._folder(job_id) / "job.json"
        if not path.is_file():
            raise FluentError("FLUENT_JOB_NOT_FOUND", "CFD job was not found.", 404)
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            # Older Fluent-only receipts stay readable; old prepared receipts require re-preparation.
            for key, default in {"is_mock": False, "requested_backend": "fluent", "effective_backend": "fluent",
                                 "fallback_reason": None, "requested_case_id": job.get("case_id"),
                                 "effective_case_id": job.get("case_id"), "attempts": []}.items():
                job.setdefault(key, default)
            if job["job_id"] != job_id or any(key not in job for key in PUBLIC_KEYS):
                raise ValueError()
            manifest = job["manifest"]
            required = {"schema_version", "journal_version", "case", "inputs", "iterations", "processors", "solver_sha256", "timeout_seconds"}
            if not isinstance(manifest, dict) or not required.issubset(manifest) or not isinstance(manifest["inputs"], dict):
                raise ValueError()
            return job
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise FluentError("FLUENT_JOB_CORRUPT", "The stored job receipt could not be read.", 409) from None

    def _save(self, job: dict):
        folder = self._folder(job["job_id"])
        job["updated_at"] = _now()
        temporary = folder / (".job-" + uuid4().hex + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(_canonical(job))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(folder / "job.json")

    @staticmethod
    def _public(job: dict) -> dict:
        return {key: job[key] for key in PUBLIC_KEYS}

    def get(self, job_id: str) -> dict:
        with self._lock:
            return self._public(self._read(job_id))

    def list(self, limit: int = 50) -> dict:
        if not self.config.jobs_root.exists():
            return {"items": []}
        folders = sorted((p for p in self.config.jobs_root.iterdir() if JOB_ID.fullmatch(p.name)), key=lambda p: p.stat().st_mtime, reverse=True)
        items = []
        for folder in folders[:min(max(limit, 1), 100)]:
            try:
                items.append(self.get(folder.name))
            except FluentError:
                continue
        return {"items": items}

    def prepare(self, request: PrepareJob) -> dict:
        self._enabled()
        if request.iterations > self.config.max_iterations or request.processors > self.config.max_processors:
            raise FluentError("FLUENT_RESOURCE_LIMIT", "Requested iterations or processors exceed configured limits.", 422)
        environment, cases, _, selected, reason, warnings = self._inventory()
        if self.config.mode == "fluent" and "FLUENT_REGISTRY_INVALID" in warnings:
            raise FluentError("FLUENT_REGISTRY_INVALID", "Review the Fluent case registry and its assets.", 503)
        case = cases.get(request.case_id)
        if not case:
            raise FluentError("FLUENT_CASE_NOT_FOUND", "Choose a registered CFD case.", 404)
        if self.config.mode == "fluent" and case.backend != "fluent":
            raise FluentError("CFD_BACKEND_MISMATCH", "Explicit Fluent mode cannot execute a mock case.", 409)
        if selected == "mock" and case.backend == "fluent":
            case = builtin_mock_case()
        if case.backend == "mock" and not self.config.mock_enabled:
            raise FluentError("CFD_MOCK_DISABLED", "Mock CFD execution is disabled.", 403)
        job_id = "fluent_" + uuid4().hex
        folder = self._folder(job_id)
        with self._lock, _exclusive(self.config.jobs_root / ".prepare.lock"):
            if sum(1 for p in self.config.jobs_root.iterdir() if JOB_ID.fullmatch(p.name)) >= 1000:
                raise FluentError("FLUENT_JOB_LIMIT", "Archive existing jobs through local operations before preparing more.", 409)
            folder.mkdir(parents=True, exist_ok=False)
            runner = self.runners[case.backend]
            inputs = runner.prepare(folder, case, self.config, request.iterations)
            fallback_case = None
            if case.backend == "fluent" and self.config.mode == "auto" and self.config.mock_enabled:
                fallback_case = builtin_mock_case()
                fallback_folder = folder / "mock_fallback"
                fallback_folder.mkdir()
                inputs.update({"mock_fallback/" + name: digest for name, digest in
                               self.runners["mock"].prepare(fallback_folder, fallback_case, self.config, request.iterations).items()})
            fallback_reason = _fallback_reason(reason) if case.backend == "mock" and self.config.mode == "auto" else None
            manifest = {"schema_version": "1.0", "journal_version": runner.version, "case": _case_snapshot(case),
                        "inputs": inputs, "iterations": request.iterations, "processors": request.processors,
                        "solver_sha256": _sha(environment["executable"]) if case.backend == "fluent" and environment["available"] else None,
                        "timeout_seconds": self.config.timeout_seconds, "requested_backend": self.config.mode,
                        "effective_backend": case.backend, "requested_case_id": request.case_id,
                        "environment": environment["report"], "fallback_reason": fallback_reason,
                        "fallback_case": _case_snapshot(fallback_case) if fallback_case else None,
                        "fallback_runner_version": self.runners["mock"].version if fallback_case else None}
            attempts = []
            if fallback_reason:
                attempts.append({"backend": "fluent", "status": "skipped", "error": dict(fallback_reason),
                                 "exit_code": None, "diagnostics": {"category": "environment", "solver_started": False}})
            job = {"job_id": job_id, "status": "prepared", "case_id": case.case_id, "iterations": request.iterations,
                   "processors": request.processors, "created_at": _now(), "updated_at": _now(),
                   "input_fingerprint": hashlib.sha256(_canonical(manifest)).hexdigest(),
                   "steps": [{"name": "prepare", "status": "completed", "detail": "Declared mock demo fingerprinted." if case.backend == "mock" else "Reviewed case and approved fallback inputs fingerprinted."}],
                   "result": None, "error": None, "manifest": manifest, "is_mock": case.backend == "mock",
                   "requested_backend": self.config.mode, "effective_backend": case.backend, "fallback_reason": fallback_reason,
                   "requested_case_id": request.case_id, "effective_case_id": case.case_id, "attempts": attempts}
            self._save(job)
            return self._public(job)

    def _validate_prepared(self, job: dict):
        self._enabled()
        manifest = job["manifest"]
        if "effective_backend" not in manifest:
            raise FluentError("FLUENT_INPUT_CHANGED", "Prepare a new job with the current CFD runner contract.", 409)
        if self.config.mode != manifest["requested_backend"]:
            raise FluentError("FLUENT_INPUT_CHANGED", "CFD mode changed. Prepare and confirm a new job.", 409)
        case = CaseSpec.model_validate(manifest["case"])
        if case.backend == "mock":
            if not self.config.mock_enabled:
                raise FluentError("CFD_MOCK_DISABLED", "Mock CFD execution is disabled.", 403)
            current_case = builtin_mock_case() if case.case_id == "mock_cfd_demo" else self.config.cases().get(case.case_id)
        else:
            current_case = self.config.cases().get(case.case_id)
        if current_case is None:
            raise FluentError("FLUENT_CASE_REVOKED", "The prepared case is no longer registered.", 409)
        folder = self._folder(job["job_id"])
        environment = {"available": False, "executable": None}
        unavailable = None
        valid = _case_snapshot(current_case) == manifest["case"] and hashlib.sha256(_canonical(manifest)).hexdigest() == job["input_fingerprint"]
        valid = valid and all(job[name] == manifest[name] for name in ("iterations", "processors", "requested_backend", "effective_backend", "requested_case_id", "fallback_reason"))
        valid = valid and job["is_mock"] == (case.backend == "mock") and job["case_id"] == case.case_id and job["effective_case_id"] == case.case_id
        valid = valid and self.runners[case.backend].version == manifest["journal_version"]
        for name, digest in manifest["inputs"].items():
            path = folder / name
            valid = valid and path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()) and _sha(path) == digest
        if case.backend == "fluent":
            environment = self._detect(self.config.executable)
            unavailable = ("FLUENT_DISABLED" if not self.config.enabled else
                           "FLUENT_EXECUTION_DISABLED" if not self.config.execution_enabled else
                           "FLUENT_SOLVER_NOT_FOUND" if not environment["available"] else None)
            if environment["available"]:
                valid = valid and _sha(environment["executable"]) == manifest["solver_sha256"]
            valid = valid and _sha(self.config.asset(current_case.case_file)) == manifest["inputs"]["input.cas.h5"]
            if current_case.data_file:
                valid = valid and _sha(self.config.asset(current_case.data_file)) == manifest["inputs"]["input.dat.h5"]
            if self.config.mode == "fluent":
                if not self.config.execution_enabled:
                    raise FluentError("FLUENT_EXECUTION_DISABLED", "Real Fluent execution is disabled.", 403)
                if not environment["available"]:
                    raise FluentError("FLUENT_SOLVER_NOT_FOUND", "Configure a local Fluent executable.", 503)
        if manifest["fallback_case"]:
            valid = valid and manifest["fallback_case"] == _case_snapshot(builtin_mock_case()) and manifest["fallback_runner_version"] == self.runners["mock"].version
        if not valid or job["iterations"] > self.config.max_iterations or job["processors"] > self.config.max_processors or manifest["timeout_seconds"] != self.config.timeout_seconds:
            raise FluentError("FLUENT_INPUT_CHANGED", "Case, runner, solver, limits, or prepared inputs changed. Prepare a new job.", 409)
        return environment, unavailable

    def run(self, job_id: str, request: RunJob) -> dict:
        self._enabled()
        with self._lock:
            job = self._read(job_id)
            if request.input_fingerprint != job["input_fingerprint"]:
                raise FluentError("FLUENT_STALE_CONFIRMATION", "The confirmed input fingerprint does not match this job.", 409)
            if job["status"] != "prepared":
                return self._public(job)
            lease = _exclusive(self.config.jobs_root / ".worker.lock")
            lease.__enter__()
            try:
                job = self._read(job_id)
                if request.input_fingerprint != job["input_fingerprint"]:
                    raise FluentError("FLUENT_STALE_CONFIRMATION", "The confirmed input fingerprint does not match this job.", 409)
                if job["status"] != "prepared":
                    lease.__exit__(None, None, None)
                    return self._public(job)
                for path in self.config.jobs_root.glob("fluent_*/job.json"):
                    previous = self._read(path.parent.name)
                    if previous["status"] in {"running", "interrupted"}:
                        if previous["status"] == "running":
                            previous["status"] = "interrupted"
                            previous["error"] = {"code": "FLUENT_WORKER_INTERRUPTED", "message": "Worker ownership was lost; reconcile the process locally."}
                            self._save(previous)
                        raise FluentError("FLUENT_RECOVERY_REQUIRED", "Reconcile an interrupted job locally before starting another worker.", 409)
                self._validate_prepared(job)
                job["status"] = "running"
                job["steps"].append({"name": "execute", "status": "running", "detail": "Confirmed immutable inputs submitted to the selected CFD runner."})
                self._save(job)
                worker = Thread(target=self._execute, args=(job_id, lease), name=job_id, daemon=True)
                self._threads[job_id] = worker
                worker.start()
                return self._public(job)
            except Exception:
                lease.__exit__(None, None, None)
                raise

    @staticmethod
    def _attempt(backend: str, outcome: RunnerOutcome) -> dict:
        return {"backend": backend, "status": outcome.status, "error": outcome.error,
                "exit_code": outcome.exit_code, "diagnostics": outcome.diagnostics}

    def _execute(self, job_id: str, lease):
        job = self._read(job_id)
        folder = self._folder(job_id)
        try:
            manifest = job["manifest"]
            case = CaseSpec.model_validate(manifest["case"])
            backend = case.backend
            # Recheck live revocation and the resolved executable immediately before
            # execution, then use exactly that checked path rather than discovering again.
            environment, reason = self._validate_prepared(job)

            def started(details):
                job["process"] = details
                self._save(job)

            context = RunnerContext(folder, case, environment["executable"], job["iterations"], job["processors"], self.config.timeout_seconds)
            if backend == "fluent" and reason:
                outcome = RunnerOutcome("skipped", error=_fallback_reason(reason),
                                        diagnostics={"category": "environment", "solver_started": False}, fallback_eligible=True)
            else:
                outcome = self.runners[backend].execute(context, started)
            job["attempts"].append(self._attempt(backend, outcome))
            if outcome.fallback_eligible and manifest["fallback_case"] and self.config.mode == "auto" and self.config.mock_enabled:
                # A long startup attempt may outlive a case revocation or input edit.
                # Revalidate the approved demo and original case before changing backend.
                self._validate_prepared(job)
                job["fallback_reason"] = dict(outcome.error)
                case = CaseSpec.model_validate(manifest["fallback_case"])
                backend = "mock"
                job.update(effective_backend="mock", effective_case_id=case.case_id, is_mock=True)
                self._save(job)
                context = RunnerContext(folder / "mock_fallback", case, None, job["iterations"], job["processors"], self.config.timeout_seconds)
                outcome = self.runners["mock"].execute(context, started)
                outcome.outputs = {"mock_fallback/" + name: digest for name, digest in outcome.outputs.items()}
                job["attempts"].append(self._attempt("mock", outcome))
            job["status"] = "failed" if outcome.status == "skipped" else outcome.status
            job["result"], job["error"], job["outputs"], job["exit_code"] = outcome.result, outcome.error, outcome.outputs, outcome.exit_code
            if job["result"] is not None:
                job["result"].update(is_mock=backend == "mock", requested_backend=job["requested_backend"], effective_backend=backend,
                                     fallback_reason=job["fallback_reason"], requested_case_id=job["requested_case_id"],
                                     effective_case_id=case.case_id, attempts=list(job["attempts"]))
            if job["status"] == "completed":
                job["steps"][-1].update(status="completed", detail="Declared mock demonstration completed; no CFD solver executed." if backend == "mock" else "Fluent wrote case/data execution evidence.")
                job["steps"].append({"name": "validate", "status": job["result"]["validation"]["status"], "detail": "Independent rules checked only the explicitly reported quantities."})
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = exc.public() if isinstance(exc, FluentError) else {"code": "CFD_WORKER_FAILED", "message": "The CFD workflow failed. Review local evidence."}
        finally:
            if job["status"] != "completed":
                job["steps"][-1].update(status=job["status"], detail=(job.get("error") or {}).get("message", "Worker failed."))
            try:
                with self._lock:
                    self._save(job)
                    (folder / "report.md").write_text(build_report(self._public(job)), encoding="utf-8")
            finally:
                lease.__exit__(None, None, None)

    def report(self, job_id: str) -> dict:
        return {"job_id": job_id, "markdown": build_report(self.get(job_id))}


CFDService = FluentService

__all__ = ["CFDService", "FluentService", "render_journal"]
