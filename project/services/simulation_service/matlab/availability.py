from __future__ import annotations

import importlib
import platform
import sys
from typing import Any, Callable

from .config import MatlabIntegrationConfig
from .discovery import MatlabDiscoveryResult, discover_matlab, recommended_engine_install_command


def check_matlab_engine_importable(import_engine: Callable[[], object] | None = None) -> dict[str, Any]:
    try:
        module = import_engine() if import_engine is not None else importlib.import_module("matlab.engine")
    except Exception:
        return {
            "engine_importable": False,
            "reason": "engine_not_installed",
            "module": None,
        }
    return {
        "engine_importable": True,
        "reason": "importable",
        "module": module,
    }


def assess_matlab_availability(
    config: MatlabIntegrationConfig,
    *,
    import_engine: Callable[[], object] | None = None,
    discovery: MatlabDiscoveryResult | None = None,
    check_engine_import: bool = True,
) -> dict[str, Any]:
    found = discovery or discover_matlab(config)
    import_status = (
        check_matlab_engine_importable(import_engine)
        if check_engine_import
        else {"engine_importable": False, "reason": "not_checked", "module": None}
    )
    engine_importable = bool(import_status.get("engine_importable"))
    license_confirmed = bool(config.operator_confirmed_license)
    engine_start_allowed = bool(config.enabled and config.allow_engine_start)
    if not config.enabled:
        status = "disabled"
        message = "MATLAB integration is disabled by default."
    elif config.require_license_confirmation and not license_confirmed:
        status = "license_not_confirmed"
        message = "Operator license confirmation is required before MATLAB engine startup."
    elif not found.matlab_exe_found:
        status = "matlab_not_found"
        message = "MATLAB root was scanned, but matlab.exe was not found."
    elif not config.allow_engine_start:
        status = "engine_start_not_allowed"
        message = "MATLAB engine startup is disabled by configuration."
    elif not engine_importable:
        status = "engine_not_installed"
        message = "MATLAB Engine for Python is not importable."
    else:
        status = "available"
        message = "MATLAB Engine for Python is importable; engine startup remains explicit."

    install_command = recommended_engine_install_command(found, "python")
    return {
        "status": status,
        "available": status == "available",
        "message": message,
        "discovery": found,
        "engine_importable": engine_importable,
        "engine_import_reason": str(import_status.get("reason") or ""),
        "engine_start_allowed": engine_start_allowed,
        "license_confirmed_by_operator": license_confirmed,
        "api_enabled": bool(config.allow_api),
        "demo_run_allowed": bool(config.allow_demo_run),
        "safe_to_run_demo": bool(
            status == "available"
            and config.allow_api
            and config.allow_demo_run
            and (license_confirmed or not config.require_license_confirmation)
        ),
        "engine_install_command": install_command,
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
    }


__all__ = ["assess_matlab_availability", "check_matlab_engine_importable"]
