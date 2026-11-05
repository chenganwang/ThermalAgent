from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
from typing import Any


COMPONENT_REQUIREMENTS: dict[str, bool] = {
    "api": True,
    "configuration": True,
    "database": True,
    "retrieval": True,
    "index": True,
    "matlab": False,
    "simulation": False,
}

_FAILURE_STATUSES = {"error", "failed", "not_ready", "pending", "unavailable"}
_VALID_STATUSES = _FAILURE_STATUSES | {"degraded", "disabled", "ready"}
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_SAFE_ERROR_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,79}$")
_SENSITIVE_OR_PATH = re.compile(
    r"password|secret|token|api[_-]?key|mysql_password|[A-Za-z]:[\\/]|(?:^|\s)/(?:home|users?|var|etc|opt|tmp)/",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_readiness_state() -> dict[str, Any]:
    started_at = utc_now()
    return {
        "checks": {
            component: {
                "component": component,
                "status": "pending",
                "started_at": started_at,
                "finished_at": None,
                "error_code": None,
                "error_type": None,
                "safe_message": "Check has not completed.",
                "required": required,
            }
            for component, required in COMPONENT_REQUIREMENTS.items()
        },
        "warnings": [],
    }


def record_readiness_check(
    state: dict[str, Any],
    component: str,
    status: str,
    *,
    error_code: str | None = None,
    error_type: str | None = None,
    safe_message: str,
) -> None:
    if component not in COMPONENT_REQUIREMENTS:
        raise ValueError(f"unknown readiness component: {component}")
    checks = state.setdefault("checks", {})
    previous = checks.get(component) if isinstance(checks.get(component), Mapping) else {}
    checks[component] = {
        "component": component,
        "status": status if status in _VALID_STATUSES else "not_ready",
        "started_at": previous.get("started_at") or utc_now(),
        "finished_at": utc_now(),
        "error_code": error_code,
        "error_type": error_type,
        "safe_message": safe_message,
        "required": COMPONENT_REQUIREMENTS[component],
    }


def _safe_text(value: object, default: str) -> str:
    if not isinstance(value, str):
        return default
    text = " ".join(value.strip().split())[:240]
    if not text or _SENSITIVE_OR_PATH.search(text):
        return default
    return text


def _safe_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _safe_check(component: str, raw: object) -> dict[str, Any]:
    required_default = COMPONENT_REQUIREMENTS[component]
    if not isinstance(raw, Mapping):
        raw = {}
    status = str(raw.get("status") or "pending").lower()
    if status not in _VALID_STATUSES:
        status = "not_ready"
    return {
        "component": component,
        "status": status,
        "started_at": _safe_timestamp(raw.get("started_at")),
        "finished_at": _safe_timestamp(raw.get("finished_at")),
        "error_code": raw.get("error_code") if isinstance(raw.get("error_code"), str) and _SAFE_CODE.fullmatch(raw["error_code"]) else None,
        "error_type": raw.get("error_type") if isinstance(raw.get("error_type"), str) and _SAFE_ERROR_TYPE.fullmatch(raw["error_type"]) else None,
        "safe_message": _safe_text(raw.get("safe_message"), "Diagnostic detail unavailable."),
        "required": required_default,
    }


def build_readiness_payload(raw_state: object) -> dict[str, Any]:
    state = raw_state if isinstance(raw_state, Mapping) else {}
    raw_checks = state.get("checks") if isinstance(state.get("checks"), Mapping) else {}
    checks = {
        component: _safe_check(component, raw_checks.get(component))
        for component in COMPONENT_REQUIREMENTS
    }
    required_failures = [
        component
        for component, check in checks.items()
        if check["required"] and check["status"] in _FAILURE_STATUSES
    ]
    optional_failures = [
        component
        for component, check in checks.items()
        if not check["required"] and check["status"] in _FAILURE_STATUSES
    ]
    warnings = []
    for item in state.get("warnings") if isinstance(state.get("warnings"), list) else []:
        if not isinstance(item, str) or not item:
            continue
        safe_item = _safe_text(item, "Diagnostic warning unavailable.")
        if safe_item not in warnings:
            warnings.append(safe_item)
    warnings.extend(
        component
        for component, check in checks.items()
        if check["status"] == "degraded" and component not in warnings
    )
    warnings.extend(component for component in optional_failures if component not in warnings)
    if required_failures:
        status = "not_ready"
    elif optional_failures or warnings:
        status = "degraded"
    else:
        status = "ready"
    return {
        "status": status,
        "ready": not required_failures,
        "checks": checks,
        "required_failures": required_failures,
        "optional_failures": optional_failures,
        "warnings": warnings,
    }


__all__ = [
    "COMPONENT_REQUIREMENTS",
    "build_readiness_payload",
    "new_readiness_state",
    "record_readiness_check",
    "utc_now",
]
