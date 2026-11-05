from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class SimulationConfig:
    enabled: bool
    history_backend: str
    history_dir: Path
    history_database_url: str
    history_database_enabled: bool
    history_db_auto_create: bool
    history_query_limit_default: int
    history_query_limit_max: int
    migration_dry_run_allow_external: bool
    migration_package_dir: Path
    migration_auto_apply: bool
    default_backend: str
    matlab_enabled: bool
    matlab_engine_real_execution_enabled: bool
    matlab_engine_start_timeout_sec: int
    matlab_engine_fake_for_test: bool
    matlab_allowed_functions: tuple[str, ...]
    tool_calling_enabled: bool
    mock_allow_failure_modes: bool
    project_root: Path

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["history_dir"] = str(self.history_dir)
        data["migration_package_dir"] = str(self.migration_package_dir)
        data["project_root"] = str(self.project_root)
        return data


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


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


def load_simulation_config(project_root: Path | None = None) -> SimulationConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    default_backend = (
        os.getenv("SIMULATION_DEFAULT_BACKEND")
        or os.getenv("SIMULATION_DEFAULT_ADAPTER")
        or "mock"
    ).strip().lower()
    return SimulationConfig(
        enabled=_env_bool("SIMULATION_ENABLED", True),
        history_backend=(os.getenv("SIMULATION_HISTORY_BACKEND") or "memory").strip().lower(),
        history_dir=_env_path("SIMULATION_HISTORY_DIR", Path("runtime/simulation/history"), base=root),
        history_database_url=(os.getenv("SIMULATION_HISTORY_DATABASE_URL") or "").strip(),
        history_database_enabled=_env_bool("SIMULATION_HISTORY_DATABASE_ENABLED", False),
        history_db_auto_create=_env_bool("SIMULATION_HISTORY_DB_AUTO_CREATE", False),
        history_query_limit_default=_env_int("SIMULATION_HISTORY_QUERY_LIMIT_DEFAULT", 50),
        history_query_limit_max=_env_int("SIMULATION_HISTORY_QUERY_LIMIT_MAX", 200),
        migration_dry_run_allow_external=_env_bool("SIMULATION_MIGRATION_DRY_RUN_ALLOW_EXTERNAL", False),
        migration_package_dir=_env_path(
            "SIMULATION_MIGRATION_PACKAGE_DIR",
            Path("services/simulation_service/migrations"),
            base=root,
        ),
        migration_auto_apply=_env_bool("SIMULATION_MIGRATION_AUTO_APPLY", False),
        default_backend=default_backend or "mock",
        matlab_enabled=_env_bool("MATLAB_SIMULATION_ENABLED", False),
        matlab_engine_real_execution_enabled=_env_bool("MATLAB_ENGINE_REAL_EXECUTION_ENABLED", False),
        matlab_engine_start_timeout_sec=_env_int("MATLAB_ENGINE_START_TIMEOUT_SEC", 30),
        matlab_engine_fake_for_test=_env_bool("MATLAB_ENGINE_FAKE_FOR_TEST", False),
        matlab_allowed_functions=tuple(
            item.strip()
            for item in (os.getenv("MATLAB_ALLOWED_FUNCTIONS") or "plus,minus,times,mtimes").split(",")
            if item.strip()
        ),
        tool_calling_enabled=_env_bool("SIMULATION_TOOL_CALLING_ENABLED", False),
        mock_allow_failure_modes=_env_bool("SIMULATION_MOCK_ALLOW_FAILURE_MODES", True),
        project_root=root,
    )


__all__ = ["SimulationConfig", "load_simulation_config"]
