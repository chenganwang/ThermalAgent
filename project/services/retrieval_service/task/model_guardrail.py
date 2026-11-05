from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .calculation_intent import is_lookup_range_query
from .model_prompt import ALLOWED_MODEL_CANDIDATE_TOOLS, ALLOWED_MODEL_TASK_TYPES
from .normalizer import normalize_query
from .property_lookup import is_property_lookup_query


MODEL_FLAG_KEYS = (
    "needs_visualization",
    "needs_report",
    "needs_comparison",
    "needs_simulation",
    "is_property_lookup",
    "is_irrelevant_or_analogy",
)


def _base_result(
    *,
    model_available: bool,
    raw_output: Any = None,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "model_available": model_available,
        "used_for_routing": False,
        "task_type": "unknown",
        "needs_calculation": False,
        "candidate_tools": [],
        "flags": {
            "needs_visualization": False,
            "needs_report": False,
            "needs_comparison": False,
            "needs_simulation": False,
            "is_property_lookup": False,
            "is_irrelevant_or_analogy": False,
        },
        "confidence": 0.0,
        "raw_output": raw_output,
        "warnings": warnings or [],
        "error": error,
    }


def _bool_field(value: Any, field_name: str, warnings: list[str]) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    warnings.append(f"non_bool_{field_name}_coerced")
    return False


def _confidence(value: Any, warnings: list[str]) -> float:
    if isinstance(value, bool):
        warnings.append("invalid_confidence_coerced")
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        warnings.append("invalid_confidence_coerced")
        return 0.0
    if number < 0.0 or number > 1.0:
        warnings.append("confidence_clamped")
    return round(max(0.0, min(1.0, number)), 4)


def _model_flags(raw_result: Mapping[str, Any], warnings: list[str]) -> dict[str, bool]:
    nested = raw_result.get("flags")
    nested_flags = nested if isinstance(nested, Mapping) else {}
    flags: dict[str, bool] = {}
    for key in MODEL_FLAG_KEYS:
        raw_value = raw_result.get(key, nested_flags.get(key))
        flags[key] = _bool_field(raw_value, key, warnings)
    return flags


def _is_standard_range_query(query: str | None) -> bool:
    if not query:
        return False
    normalized = normalize_query(query)
    if not is_lookup_range_query(normalized):
        return False
    return bool(
        re.search(
            r"\b(?:ASHRAE|OCP|A1|A2|A3|A4|H1|W17|W27|W32|W40|W45|W\+)\b|Open Compute Project",
            normalized,
            re.IGNORECASE,
        )
    )


def validate_model_task_result(raw_result: Any, query: str | None = None) -> dict[str, Any]:
    """Validate model task-understanding output for offline comparison only."""

    if not isinstance(raw_result, Mapping):
        return _base_result(
            model_available=False,
            raw_output=raw_result,
            warnings=["invalid_json"],
            error="invalid_json",
        )

    warnings: list[str] = []
    raw_task_type = raw_result.get("task_type")
    if raw_task_type == "simulation_result":
        task_type = "simulation_readiness"
        warnings.append("simulation_result_downgraded")
    elif isinstance(raw_task_type, str) and raw_task_type in ALLOWED_MODEL_TASK_TYPES:
        task_type = raw_task_type
    else:
        task_type = "unknown"
        if raw_task_type is not None:
            warnings.append("illegal_task_type")

    raw_tools = raw_result.get("candidate_tools")
    candidate_tools: list[str] = []
    illegal_tool_seen = False
    if isinstance(raw_tools, list):
        for item in raw_tools:
            tool = str(item)
            if tool in ALLOWED_MODEL_CANDIDATE_TOOLS and tool not in candidate_tools:
                candidate_tools.append(tool)
            else:
                illegal_tool_seen = True
    elif raw_tools is not None:
        illegal_tool_seen = True
    if illegal_tool_seen:
        warnings.append("illegal_candidate_tool_filtered")

    flags = _model_flags(raw_result, warnings)
    needs_calculation = _bool_field(raw_result.get("needs_calculation"), "needs_calculation", warnings)
    confidence = _confidence(raw_result.get("confidence"), warnings)

    if task_type == "visualization":
        flags["needs_visualization"] = True
    if task_type == "report":
        flags["needs_report"] = True
    if task_type == "comparison":
        flags["needs_comparison"] = True
    if task_type == "simulation_readiness":
        flags["needs_simulation"] = True
    if task_type == "property_lookup":
        flags["is_property_lookup"] = True
    if task_type == "irrelevant_or_analogy":
        flags["is_irrelevant_or_analogy"] = True

    if query and is_property_lookup_query(query):
        flags["is_property_lookup"] = True
        if "liquid_flow_rate_required" in candidate_tools:
            candidate_tools = [tool for tool in candidate_tools if tool != "liquid_flow_rate_required"]
            warnings.append("glycol_property_lookup_blocks_flow_tool")
        if needs_calculation:
            needs_calculation = False
            warnings.append("property_lookup_blocks_calculation")
        if task_type == "calculation":
            task_type = "property_lookup"

    if _is_standard_range_query(query):
        if needs_calculation:
            warnings.append("standard_range_lookup_blocks_calculation")
        needs_calculation = False
        if candidate_tools:
            warnings.append("standard_range_lookup_clears_candidate_tools")
        candidate_tools = []
        if task_type == "calculation":
            task_type = "retrieval"

    result = _base_result(model_available=True, raw_output=dict(raw_result), warnings=warnings, error=None)
    result.update(
        {
            "task_type": task_type,
            "needs_calculation": needs_calculation,
            "candidate_tools": candidate_tools,
            "flags": flags,
            "confidence": confidence,
        }
    )
    return result
