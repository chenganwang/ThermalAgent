from __future__ import annotations

from typing import Any

from .feature_flags import DEFAULT_FEATURE_FLAGS, env_flag, get_effective_feature_flags
from .matlab.adapter import MatlabSimulationAdapter


def build_simulation_capability(feature_flags: dict[str, bool] | None = None) -> dict[str, Any]:
    matlab_status = MatlabSimulationAdapter().status().to_dict()
    flags = dict(get_effective_feature_flags() if feature_flags is None else feature_flags)
    show_in_frontend = bool(flags.get("simulation_visible", DEFAULT_FEATURE_FLAGS["simulation_visible"]))
    requested_enabled = bool(flags.get("simulation_enabled", DEFAULT_FEATURE_FLAGS["simulation_enabled"]))
    backend_enabled = bool(matlab_status.get("enabled")) and bool(matlab_status.get("api_enabled"))
    real_matlab_available = bool(
        matlab_status.get("available")
        and matlab_status.get("engine_importable")
        and matlab_status.get("license_confirmed_by_operator")
    )
    backend_guard_passed = bool(backend_enabled and real_matlab_available)
    enabled = bool(requested_enabled and backend_guard_passed)
    safe_to_run_demo = bool(enabled and matlab_status.get("safe_to_run_demo"))

    return {
        "show_in_frontend": show_in_frontend,
        "enabled": enabled,
        "feature_enabled": requested_enabled,
        "ui_enabled_requested": requested_enabled,
        "api_enabled": bool(enabled),
        "backend_enabled": backend_enabled,
        "backend_guard_passed": backend_guard_passed,
        "requires_operator_enable": True,
        "real_matlab_available": real_matlab_available,
        "fake_engine_available_for_tests": True,
        "default_provider": "matlab",
        "provider": "matlab",
        "provider_status": str(matlab_status.get("status") or "unknown"),
        "endpoints": {
            "status": "/simulation/status",
            "matlab_status": "/simulation/matlab/status",
            "matlab_demo": "/simulation/matlab/demo",
            "catalog": "/simulation/catalog",
            "scenarios": "/simulation/scenarios",
            "models": "/simulation/models",
            "plan": "/simulation/plan",
            "run": "/simulation/run",
        },
        "providers": {
            "matlab": {
                "enabled": bool(matlab_status.get("enabled")),
                "api_enabled": bool(matlab_status.get("api_enabled")),
                "available": bool(matlab_status.get("available")),
                "real_matlab_available": real_matlab_available,
                "engine_importable": bool(matlab_status.get("engine_importable")),
                "engine_start_allowed": bool(matlab_status.get("engine_start_allowed")),
                "license_confirmed_by_operator": bool(matlab_status.get("license_confirmed_by_operator")),
                "demo_run_allowed": bool(matlab_status.get("demo_run_allowed")),
                "safe_to_run_demo": safe_to_run_demo,
                "status": str(matlab_status.get("status") or "unknown"),
                "message": str(matlab_status.get("message") or ""),
                "allowed_demos": list(matlab_status.get("allowed_demos") or []),
                "engine_type": str(matlab_status.get("engine_type") or "none"),
            }
        },
        "message": _simulation_message(show_in_frontend, requested_enabled, backend_enabled, real_matlab_available, matlab_status),
    }


def _simulation_message(
    show_in_frontend: bool,
    requested_enabled: bool,
    backend_enabled: bool,
    real_matlab_available: bool,
    matlab_status: dict[str, Any],
) -> str:
    if not show_in_frontend:
        return "Simulation UI is hidden by frontend feature flag."
    if not requested_enabled:
        return "Simulation UI can be shown, but execution is disabled by frontend feature flag."
    if not backend_enabled:
        return "Simulation UI requested execution, but backend MATLAB integration guards are still blocking it."
    if not real_matlab_available:
        return "Simulation execution is not available until MATLAB Engine and operator license confirmation are ready."
    return str(matlab_status.get("message") or "Simulation execution is available through the controlled MATLAB adapter.")


__all__ = ["build_simulation_capability", "env_flag"]
