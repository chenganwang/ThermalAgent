from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from .contracts import CaseSpec, FluentError


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {"true", "1", "yes", "on"}


def _bounded(name: str, default: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        result = int(raw)
        if not 1 <= result <= maximum:
            raise ValueError()
        return result
    except ValueError:
        raise FluentError("FLUENT_CONFIGURATION_INVALID", "Fluent resource limits are invalid.", 503) from None


@dataclass(frozen=True)
class FluentConfig:
    enabled: bool
    execution_enabled: bool
    executable: Path | None
    case_root: Path
    registry: Path
    jobs_root: Path
    max_iterations: int = 10000
    max_processors: int = 4
    timeout_seconds: int = 1800
    cfd_enabled: bool = True
    mode: str = "mock"
    mock_enabled: bool = True

    @classmethod
    def from_env(cls) -> "FluentConfig":
        root = Path(os.getenv("RAG_PROJECT_ROOT") or Path(__file__).resolve().parents[3]).resolve()

        def path(name: str, default: str) -> Path:
            value = Path(os.getenv(name) or default)
            return (value if value.is_absolute() else root / value).resolve()

        executable = os.getenv("FLUENT_EXECUTABLE", "").strip()
        # Installation roots are resolved by the environment detector, which also
        # preserves which setting supplied the path and supports Workbench roots.
        solver = path("FLUENT_EXECUTABLE", "") if executable else None
        mode = os.getenv("CFD_MODE", "mock").strip().lower()
        if mode not in {"auto", "fluent", "mock"}:
            raise FluentError("CFD_CONFIGURATION_INVALID", "CFD_MODE must be auto, fluent, or mock.", 503)
        return cls(
            enabled=_flag("FLUENT_ENABLED"), execution_enabled=_flag("FLUENT_EXECUTION_ENABLED"),
            executable=solver.resolve() if solver else None,
            case_root=path("FLUENT_CASE_ROOT", "simulation_models/fluent"),
            registry=path("FLUENT_CASE_REGISTRY", "config/fluent_cases.json"),
            jobs_root=path("FLUENT_JOBS_ROOT", "runtime/fluent/jobs"),
            max_iterations=_bounded("FLUENT_MAX_ITERATIONS", 10000, 10000),
            max_processors=_bounded("FLUENT_MAX_PROCESSORS", 4, 64),
            timeout_seconds=_bounded("FLUENT_TIMEOUT_SECONDS", 1800, 86400),
            cfd_enabled=_flag("CFD_ENABLED", True), mode=mode, mock_enabled=_flag("CFD_MOCK_ENABLED", True),
        )

    def solver_found(self) -> bool:
        from .environment import detect_environment
        return bool(detect_environment(self.executable)["report"]["solver_found"])

    def cases(self) -> dict[str, CaseSpec]:
        if not self.registry.is_file():
            return {}
        try:
            if self.registry.stat().st_size > 1_000_000:
                raise ValueError()
            payload = json.loads(self.registry.read_text(encoding="utf-8-sig"))
            if set(payload) != {"schema_version", "cases"} or payload["schema_version"] != "1.0":
                raise ValueError()
            cases = [CaseSpec.model_validate(item) for item in payload["cases"]]
            if len(cases) > 100 or len({item.case_id for item in cases}) != len(cases):
                raise ValueError()
            for item in cases:
                if item.backend == "mock":
                    if item.case_id == "mock_cfd_demo":
                        raise ValueError("The built-in demo identifier is reserved")
                    continue
                self.asset(item.case_file)
                if item.data_file:
                    self.asset(item.data_file)
            return {item.case_id: item for item in cases}
        except (OSError, ValueError, TypeError, KeyError):
            raise FluentError("FLUENT_REGISTRY_INVALID", "Review the Fluent case registry and its assets.", 503) from None

    def asset(self, relative: str) -> Path:
        candidate = (self.case_root / relative).resolve()
        if not candidate.is_relative_to(self.case_root.resolve()) or not candidate.is_file():
            raise ValueError("Case asset is outside its configured root or missing")
        return candidate
