from __future__ import annotations

from typing import Any

from services.simulation_service.matlab.availability import assess_matlab_availability
from services.simulation_service.matlab.config import load_matlab_integration_config

from ..context import ActionExecutionContext
from ..schemas import ActionHandlerResult


def matlab_environment_preconditions(_parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": True,
        "checks": [{"check_id": "engine_start_forced_false", "passed": True}],
        "warnings": [],
    }


def matlab_environment_check(
    context: ActionExecutionContext,
    _parameters: dict[str, Any],
) -> ActionHandlerResult:
    context.deadline_exceeded()
    config = load_matlab_integration_config()
    assessment = assess_matlab_availability(config, check_engine_import=True)
    discovery = assessment["discovery"]
    installed_or_discoverable = bool(
        discovery.root_exists or discovery.matlab_exe_found or discovery.engine_python_dir_found
    )
    engine_importable = bool(assessment.get("engine_importable"))
    api_enabled = bool(assessment.get("api_enabled"))
    engine_start_allowed = bool(assessment.get("engine_start_allowed"))
    license_confirmed = bool(assessment.get("license_confirmed_by_operator"))
    ready = bool(
        installed_or_discoverable
        and engine_importable
        and api_enabled
        and engine_start_allowed
        and (license_confirmed or not config.require_license_confirmation)
    )
    return ActionHandlerResult(
        success=True,
        summary={
            "installed_or_discoverable": installed_or_discoverable,
            "engine_importable": engine_importable,
            "api_enabled": api_enabled,
            "engine_start_allowed": engine_start_allowed,
            "license_confirmed": license_confirmed,
            "ready": ready,
        },
        metrics={
            "version_candidate_count": len(discovery.version_dirs),
            "multiple_versions_found": bool(discovery.multiple_versions_found),
            "engine_started": False,
            "matlab_called": False,
        },
        warnings=[] if ready else ["MATLAB execution readiness is not fully satisfied; no engine was started."],
        details={
            "integration_configured": bool(config.enabled),
            "root_configured": bool(config.matlab_root.strip()),
            "root_discoverable": bool(discovery.root_exists),
            "engine_package_discoverable": bool(discovery.engine_python_dir_found),
            "start_engine": False,
        },
    )


__all__ = ["matlab_environment_check", "matlab_environment_preconditions"]
