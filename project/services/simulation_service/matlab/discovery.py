from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any

from .config import MatlabIntegrationConfig


_VERSION_RE = re.compile(r"^R(?P<year>\d{4})(?P<release>[ab])$", re.IGNORECASE)


@dataclass(frozen=True)
class MatlabVersionCandidate:
    version: str
    version_dir: str
    matlab_exe: str | None = None
    engine_python_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatlabDiscoveryResult:
    matlab_root: str
    root_exists: bool
    version_dirs: list[str] = field(default_factory=list)
    selected_version_dir: str | None = None
    matlab_exe: str | None = None
    matlab_exe_found: bool = False
    matlab_exe_candidates: list[str] = field(default_factory=list)
    engine_python_dir: str | None = None
    engine_python_dir_found: bool = False
    engine_python_candidates: list[str] = field(default_factory=list)
    multiple_versions_found: bool = False
    candidates: list[MatlabVersionCandidate] = field(default_factory=list)
    status: str = "not_configured"
    message: str = "MATLAB root is not configured."

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data


def discover_matlab(config: MatlabIntegrationConfig) -> MatlabDiscoveryResult:
    root_text = (config.matlab_root or "").strip()
    if not root_text:
        return MatlabDiscoveryResult(
            matlab_root="",
            root_exists=False,
            status="not_configured",
            message="SIMULATION_MATLAB_ROOT is not configured.",
        )

    root = Path(root_text)
    if not root.exists() or not root.is_dir():
        return MatlabDiscoveryResult(
            matlab_root=str(root),
            root_exists=False,
            status="matlab_not_found",
            message="MATLAB root directory was not found.",
        )

    version_dirs = _version_directories(root)
    configured_version = _configured_path(config.matlab_version_dir)
    if configured_version is not None:
        version_dirs = _prepend_unique(configured_version, version_dirs)

    if not version_dirs:
        exe_candidates = _find_matlab_executables(root)
        selected_exe = _configured_path(config.matlab_exe) or _first(exe_candidates)
        selected_dir = selected_exe.parents[1] if selected_exe and selected_exe.parent.name.lower() == "bin" else None
        engine_dir = _engine_python_dir(selected_dir) if selected_dir else None
        return MatlabDiscoveryResult(
            matlab_root=str(root),
            root_exists=True,
            selected_version_dir=str(selected_dir) if selected_dir else None,
            matlab_exe=str(selected_exe) if selected_exe else None,
            matlab_exe_found=bool(selected_exe and selected_exe.exists()),
            matlab_exe_candidates=[str(path) for path in exe_candidates],
            engine_python_dir=str(engine_dir) if engine_dir else None,
            engine_python_dir_found=bool(engine_dir and engine_dir.exists()),
            engine_python_candidates=[str(engine_dir)] if engine_dir and engine_dir.exists() else [],
            status="available" if selected_exe else "matlab_not_found",
            message="MATLAB executable was found." if selected_exe else "No MATLAB version directory or executable was found.",
        )

    candidates = [_candidate_for(version_dir) for version_dir in version_dirs]
    selected = _select_candidate(candidates, config)
    exe_candidates = [Path(candidate.matlab_exe) for candidate in candidates if candidate.matlab_exe]
    configured_exe = _configured_path(config.matlab_exe)
    if configured_exe is not None:
        exe_candidates = _prepend_unique(configured_exe, exe_candidates)
    engine_candidates = [Path(candidate.engine_python_dir) for candidate in candidates if candidate.engine_python_dir]

    matlab_exe = configured_exe or (Path(selected.matlab_exe) if selected and selected.matlab_exe else _first(exe_candidates))
    engine_python = Path(selected.engine_python_dir) if selected and selected.engine_python_dir else _first(engine_candidates)
    selected_version_dir = Path(selected.version_dir) if selected else None

    status = "available" if matlab_exe and matlab_exe.exists() else "matlab_not_found"
    message = "MATLAB installation candidate was discovered." if status == "available" else "MATLAB version directories were found, but matlab.exe was not found."
    return MatlabDiscoveryResult(
        matlab_root=str(root),
        root_exists=True,
        version_dirs=[str(path) for path in version_dirs],
        selected_version_dir=str(selected_version_dir) if selected_version_dir else None,
        matlab_exe=str(matlab_exe) if matlab_exe else None,
        matlab_exe_found=bool(matlab_exe and matlab_exe.exists()),
        matlab_exe_candidates=[str(path) for path in exe_candidates],
        engine_python_dir=str(engine_python) if engine_python else None,
        engine_python_dir_found=bool(engine_python and engine_python.exists()),
        engine_python_candidates=[str(path) for path in engine_candidates],
        multiple_versions_found=len(version_dirs) > 1,
        candidates=candidates,
        status=status,
        message=message,
    )


def recommended_engine_install_command(discovery: MatlabDiscoveryResult, python_command: str = "python") -> str | None:
    engine_dir = discovery.engine_python_dir
    if not engine_dir or not discovery.engine_python_dir_found:
        return None
    return f'cd "{engine_dir}"\n{python_command} -m pip install .'


def _version_directories(root: Path) -> list[Path]:
    directories = [path for path in root.iterdir() if path.is_dir()]
    versioned = [path for path in directories if _VERSION_RE.match(path.name)]
    if not versioned:
        versioned = directories
    return sorted(versioned, key=_version_sort_key, reverse=True)


def _version_sort_key(path: Path) -> tuple[int, int, str]:
    match = _VERSION_RE.match(path.name)
    if not match:
        return (0, 0, path.name.lower())
    release_order = {"a": 1, "b": 2}.get(match.group("release").lower(), 0)
    return (int(match.group("year")), release_order, path.name.lower())


def _candidate_for(version_dir: Path) -> MatlabVersionCandidate:
    exe = version_dir / "bin" / "matlab.exe"
    engine_dir = _engine_python_dir(version_dir)
    return MatlabVersionCandidate(
        version=version_dir.name,
        version_dir=str(version_dir),
        matlab_exe=str(exe) if exe.exists() else None,
        engine_python_dir=str(engine_dir) if engine_dir.exists() else None,
    )


def _engine_python_dir(version_dir: Path | None) -> Path | None:
    if version_dir is None:
        return None
    return version_dir / "extern" / "engines" / "python"


def _select_candidate(
    candidates: list[MatlabVersionCandidate],
    config: MatlabIntegrationConfig,
) -> MatlabVersionCandidate | None:
    configured_version = _configured_path(config.matlab_version_dir)
    if configured_version is not None:
        for candidate in candidates:
            if Path(candidate.version_dir) == configured_version:
                return candidate
    with_exe = [candidate for candidate in candidates if candidate.matlab_exe]
    if with_exe:
        return with_exe[0]
    return candidates[0] if candidates else None


def _find_matlab_executables(root: Path) -> list[Path]:
    try:
        candidates = list(root.rglob("matlab.exe"))
    except OSError:
        return []
    return sorted(candidates, key=lambda path: (0 if path.parent.name.lower() == "bin" else 1, str(path).lower()))


def _configured_path(raw: str | None) -> Path | None:
    text = (raw or "").strip()
    return Path(text) if text else None


def _prepend_unique(first: Path, values: list[Path]) -> list[Path]:
    result = [first]
    result.extend(path for path in values if path != first)
    return result


def _first(values: list[Path]) -> Path | None:
    return values[0] if values else None


__all__ = [
    "MatlabDiscoveryResult",
    "MatlabVersionCandidate",
    "discover_matlab",
    "recommended_engine_install_command",
]
