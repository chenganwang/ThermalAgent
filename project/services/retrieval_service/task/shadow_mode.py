from __future__ import annotations

from collections.abc import Mapping
from typing import Any


FLAG_KEYS = (
    "needs_calculation",
    "needs_visualization",
    "needs_report",
    "needs_comparison",
    "needs_simulation",
    "is_property_lookup",
    "is_irrelevant_or_analogy",
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        if isinstance(mapped, Mapping):
            return mapped
    return {}


def _rule_flags(rule: Mapping[str, Any]) -> dict[str, bool]:
    return {key: bool(rule.get(key)) for key in FLAG_KEYS}


def _model_flags(model: Mapping[str, Any]) -> dict[str, bool]:
    nested = model.get("flags")
    nested_flags = nested if isinstance(nested, Mapping) else {}
    return {key: bool(model.get(key, nested_flags.get(key))) for key in FLAG_KEYS}


def _infer_model_enabled_by_config(model: Mapping[str, Any]) -> bool:
    warnings = {str(item) for item in model.get("warnings") or []}
    if "model_assist_disabled" in warnings or "disabled_by_config" in warnings:
        return False
    return bool(model.get("enabled"))


def build_task_model_assist_metadata(
    query: str,
    rule_result: dict[str, Any],
    model_result: dict[str, Any],
    *,
    model_enabled_by_config: bool | None = None,
    shadow_enabled: bool = True,
) -> dict[str, Any]:
    """Build shadow metadata comparing rule and model-assist results.

    The metadata is intentionally read-only and never used for routing in this
    phase. It also avoids copying full answers, sources, or source previews.
    """

    _ = query
    rule = dict(_as_mapping(rule_result))
    model = dict(_as_mapping(model_result))
    rule_tools = list(rule.get("candidate_tools") or [])
    model_tools = list(model.get("candidate_tools") or [])
    rule_task_type = rule.get("task_type")
    model_task_type = model.get("task_type")
    model_available = bool(model.get("model_available"))
    rule_flags = _rule_flags(rule)
    model_flags = _model_flags(model)
    disagreement_fields: list[str] = []

    if model_available and model_task_type is not None:
        if model_task_type != rule_task_type:
            disagreement_fields.append("task_type")
        if model_tools != rule_tools:
            disagreement_fields.append("candidate_tools")
        for key in FLAG_KEYS:
            if model_flags.get(key) != rule_flags.get(key):
                disagreement_fields.append(key)

    if model_enabled_by_config is None:
        model_enabled_by_config = _infer_model_enabled_by_config(model)

    return {
        "enabled": bool(shadow_enabled),
        "used_for_routing": False,
        "model_available": model_available,
        "model_enabled_by_config": bool(model_enabled_by_config),
        "rule_task_type": rule_task_type,
        "model_task_type": model_task_type,
        "rule_candidate_tools": rule_tools,
        "model_candidate_tools": model_tools,
        "disagreement_with_rule": bool(disagreement_fields),
        "confidence": model.get("confidence"),
        "rule_flags": rule_flags,
        "model_flags": model_flags,
        "disagreement_fields": disagreement_fields,
        "guardrail_applied": model_available and model_task_type is not None,
        "warnings": list(model.get("warnings") or []),
        "error": model.get("error"),
    }
