from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MatlabStatus:
    enabled: bool
    available: bool
    status: str
    engine_importable: bool
    engine_start_allowed: bool
    license_confirmed_by_operator: bool
    api_enabled: bool
    demo_run_allowed: bool
    safe_to_run_demo: bool
    message: str
    matlab_root: str = ""
    root_exists: bool = False
    version_dirs: list[str] = field(default_factory=list)
    selected_version_dir: str | None = None
    matlab_exe: str | None = None
    matlab_exe_found: bool = False
    matlab_exe_candidates: list[str] = field(default_factory=list)
    engine_python_dir: str | None = None
    engine_python_dir_found: bool = False
    engine_python_candidates: list[str] = field(default_factory=list)
    multiple_versions_found: bool = False
    engine_install_command: str | None = None
    python_version: str | None = None
    python_executable: str | None = None
    allowed_demos: list[str] = field(default_factory=list)
    engine_type: str = "none"
    matlab_version: str | None = None
    checked_at: str = field(default_factory=utc_now_iso)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatlabSimulationResult:
    success: bool
    status: str
    demo_name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] = field(default_factory=dict)
    engine_type: str = "none"
    is_real_matlab: bool = False
    is_fake: bool = False
    matlab_version: str | None = None
    evidence_id: str | None = None
    evidence_path: str | None = None
    human_validated: bool = False
    license_confirmed_by_operator: bool = False
    duration_ms: int | None = None
    formula: str | None = None
    assumptions: list[str] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)
    missing_parameters: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatlabConnectionStatus:
    """Public, JSON-safe status for the real MATLAB Engine boundary."""

    configured: bool = False
    available: bool = False
    connected: bool = False
    engine_import_ok: bool = False
    engine_started: bool = False
    matlab_version: str | None = None
    python_version: str | None = None
    matlab_root: str | None = None
    engine_error: dict[str, Any] | None = None
    last_check_at: str | None = None
    execution_mode: str = "unavailable"
    uses_real_matlab: bool = False
    runtime_state: str = "stopped"
    matlab_root_detected: bool = False
    dispatcher_callable: bool = False
    owned_session: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatlabExecutionRequest:
    plan_id: str
    model_id: str
    matlab_entrypoint: str
    inputs: dict[str, Any]
    confirmed: bool = False
    timeout_seconds: int = 60
    execution_id: str = field(default_factory=lambda: f"matlab-exec-{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatlabExecutionResult:
    executed: bool
    status: str
    plan_id: str
    model_id: str
    matlab_entrypoint: str
    execution_id: str = field(default_factory=lambda: f"matlab-exec-{uuid4().hex}")
    backend: str = "matlab"
    execution_mode: str = "unavailable"
    uses_real_matlab: bool = False
    matlab_version: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    result: dict[str, Any] = field(default_factory=dict)
    result_files: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    cfd_executed: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "MatlabConnectionStatus",
    "MatlabExecutionRequest",
    "MatlabExecutionResult",
    "MatlabSimulationResult",
    "MatlabStatus",
    "utc_now_iso",
]
