from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path


DEFAULT_MATLAB_ROOT = ""


@dataclass(frozen=True)
class MatlabIntegrationConfig:
    enabled: bool
    allow_engine_start: bool
    allow_api: bool
    allow_demo_run: bool
    require_license_confirmation: bool
    operator_confirmed_license: bool
    matlab_root: str
    matlab_version_dir: str
    matlab_exe: str
    engine_timeout_seconds: int
    max_runtime_seconds: int
    workdir: Path
    evidence_dir: Path
    allowed_demos: tuple[str, ...]
    allowed_functions: tuple[str, ...]
    operator: str
    project_root: Path

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["workdir"] = str(self.workdir)
        data["evidence_dir"] = str(self.evidence_dir)
        data["project_root"] = str(self.project_root)
        data["matlab_root_configured"] = bool(self.matlab_root.strip())
        data["matlab_root"] = self.matlab_root
        data["matlab_version_dir"] = self.matlab_version_dir
        data["matlab_exe"] = self.matlab_exe
        return data


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_path(name: str, default: Path, *, base: Path) -> Path:
    raw = os.getenv(name)
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = base / path
    return path


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name) or default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def load_matlab_integration_config(project_root: Path | None = None) -> MatlabIntegrationConfig:
    root = project_root or Path(__file__).resolve().parents[3]
    return MatlabIntegrationConfig(
        enabled=_env_bool("SIMULATION_MATLAB_ENABLED", False),
        allow_engine_start=_env_bool("SIMULATION_MATLAB_ALLOW_ENGINE_START", False),
        allow_api=_env_bool("SIMULATION_MATLAB_ALLOW_API", False),
        allow_demo_run=_env_bool("SIMULATION_MATLAB_ALLOW_DEMO_RUN", False),
        require_license_confirmation=_env_bool("SIMULATION_MATLAB_REQUIRE_LICENSE_CONFIRMATION", True),
        operator_confirmed_license=_env_bool("SIMULATION_MATLAB_OPERATOR_CONFIRMED_LICENSE", False),
        matlab_root=(os.getenv("SIMULATION_MATLAB_ROOT") or DEFAULT_MATLAB_ROOT).strip(),
        matlab_version_dir=(os.getenv("SIMULATION_MATLAB_VERSION_DIR") or "").strip(),
        matlab_exe=(os.getenv("SIMULATION_MATLAB_EXE") or "").strip(),
        engine_timeout_seconds=_env_int("SIMULATION_MATLAB_ENGINE_TIMEOUT_SECONDS", 60),
        max_runtime_seconds=_env_int("SIMULATION_MATLAB_MAX_RUNTIME_SECONDS", 120),
        workdir=_env_path("SIMULATION_MATLAB_WORKDIR", Path("runtime/simulation/matlab_workdir"), base=root),
        evidence_dir=_env_path(
            "SIMULATION_MATLAB_EVIDENCE_DIR",
            Path("runtime/simulation/evidence/matlab"),
            base=root,
        ),
        allowed_demos=_env_csv("SIMULATION_MATLAB_ALLOWED_DEMOS", "basic_numeric,heat_conduction_1d"),
        allowed_functions=_env_csv("SIMULATION_MATLAB_ALLOWED_FUNCTIONS", "plus,minus,times,mtimes,sqrt"),
        operator=(os.getenv("SIMULATION_OPERATOR") or "").strip(),
        project_root=root,
    )


__all__ = ["MatlabIntegrationConfig", "load_matlab_integration_config"]
