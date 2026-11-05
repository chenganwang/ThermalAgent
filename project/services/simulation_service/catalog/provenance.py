from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping
from uuid import uuid4

from .schemas import ExecutorDefinition, ModelDefinition, ScenarioDefinition


_SENSITIVE_KEYS = {"evidence_path", "path", "absolute_path", "local_path", "license", "password", "admin_token", "python_executable", "matlab_root", "artifacts"}


def build_evidence_summary(
    scenario: ScenarioDefinition,
    model: ModelDefinition,
    executor: ExecutorDefinition,
    result: Mapping[str, Any],
    *,
    inputs: Mapping[str, Any],
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "evidence_id": str(result.get("evidence_id") or f"catalog-{uuid4().hex}"),
        "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.version,
        "model_id": model.model_id,
        "model_version": model.version,
        "solver": model.solver,
        "engine_version": result.get("matlab_version") or executor.version,
        "is_real_solver": bool(result.get("is_real_matlab")) if model.solver == "matlab" else True,
        "human_validated": model.human_validated,
        "duration_ms": duration_ms,
        "status": str(result.get("status") or "success"),
        "model_hash": model.hash,
        "inputs": dict(inputs),
        "outputs": dict(result.get("outputs") or {}),
        "assumptions": list(result.get("assumptions") or model.assumptions),
        "warnings": list(result.get("warnings") or []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): sanitize_public_payload(v) for k, v in value.items() if not _sensitive_key(str(k))}
    if isinstance(value, list):
        return [sanitize_public_payload(x) for x in value]
    if isinstance(value, tuple):
        return [sanitize_public_payload(x) for x in value]
    if isinstance(value, str):
        return _redact_paths(value)
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in _SENSITIVE_KEYS
        or lowered.endswith("_path")
        or "password" in lowered
        or "token" in lowered
        or "license" in lowered
    )


def _redact_paths(value: str) -> str:
    value = re.sub(r"(?i)\b[a-z]:[\\/][^\s,;\]\[{}]+", "[redacted_local_path]", value)
    value = re.sub(r"(?i)file://\S+", "[redacted_local_path]", value)
    return value


__all__ = ["build_evidence_summary", "sanitize_public_payload"]
