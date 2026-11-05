from __future__ import annotations

import re
from typing import Any

from ..properties.aliases import detect_fluid, detect_property_name
from ..task.calculation_intent import is_formula_or_explanation_query
from .registry import DEFAULT_TOOL_REGISTRY, ToolRegistry
from .unit_parser import (
    normalize_text,
    parse_area_m2,
    parse_conductivity_w_mk,
    parse_mass_flow_kg_s,
    parse_plane_wall_temperature_difference_k,
    parse_thermal_resistance_k_per_w,
    parse_thickness_m,
    parse_volume_flow_m3_s,
)


PROPERTY_LOOKUP_TOOL_NAME = "coolant_property_lookup"


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _task_to_dict(task: dict[str, Any] | Any | None) -> dict[str, Any]:
    if task is None:
        return {}
    if isinstance(task, dict):
        return task
    if hasattr(task, "to_dict"):
        value = task.to_dict()
        if isinstance(value, dict):
            return value
    return {}


def _explicit_calculation_signal(text: str) -> bool:
    return _has_any(text, ("计算", "估算", "求", "算一下", "calculate", "estimate", "given", "已知"))


def _is_standards_or_range_lookup(text: str) -> bool:
    lowered = text.lower()
    standard = bool(
        re.search(r"\bASHRAE\b|\bOCP\b|\bW(?:17|27|32|40|45|\+)\b|Open Compute Project", text, re.IGNORECASE)
    )
    range_terms = _has_any(
        lowered,
        (
            "推荐",
            "允许",
            "范围",
            "干球",
            "供水温度",
            "recommended",
            "allowable",
            "range",
            "dry-bulb",
            "facility water supply",
        ),
    )
    return standard and range_terms and not _explicit_calculation_signal(text)


def _is_property_lookup(text: str) -> bool:
    lowered = text.lower()
    fluid = detect_fluid(text) is not None or _has_any(
        lowered,
        (
            "egw",
            "pgw",
            "water",
            "ethylene glycol",
            "propylene glycol",
            "glycol",
            "乙二醇",
            "丙二醇",
            "防冻液",
        ),
    )
    prop = detect_property_name(text) is not None or _has_any(
        lowered,
        (
            "cp",
            "比热",
            "比热容",
            "rho",
            "密度",
            "粘度",
            "黏度",
            "物性",
            "热导率",
        ),
    )
    flow_request = _has_any(lowered, ("流量", "l/min", "lpm", "flow rate"))
    return fluid and prop and not flow_request


def _calculation_tool_names(registry: ToolRegistry) -> set[str]:
    return {
        spec.name
        for spec in registry.list()
        if spec.domain in {"thermal_management", "hydraulics", "thermal_network"}
    }


def _is_irrelevant_or_analogy(text: str) -> bool:
    return _has_any(text, ("食堂排队", "有什么关系", "类比")) and not _explicit_calculation_signal(text)


def _is_formula_only(text: str) -> bool:
    if not _has_any(text, ("公式", "物理意义", "参数代表", "代表什么", "原理")):
        return False
    return not _explicit_calculation_signal(text)


def _hard_blocked(text: str, task: dict[str, Any]) -> bool:
    task_type = str(task.get("task_type") or "")
    if bool(task.get("is_property_lookup")) or task_type == "property_lookup":
        return True
    if bool(task.get("is_irrelevant_or_analogy")) or task_type == "irrelevant_or_analogy":
        return True
    return (
        is_formula_or_explanation_query(text)
        or _is_standards_or_range_lookup(text)
        or _is_property_lookup(text)
        or _is_irrelevant_or_analogy(text)
        or _is_formula_only(text)
    )


def _candidate_from_task(task: dict[str, Any], registry: ToolRegistry) -> str | None:
    candidates = [str(item) for item in task.get("candidate_tools") or []]
    if not candidates:
        return None
    if task.get("needs_calculation") is False:
        return None
    legal = _calculation_tool_names(registry)
    for candidate in candidates:
        if candidate in legal:
            return candidate
    return None


def _rule_score(tool_name: str, text: str) -> int:
    lowered = text.lower()
    score = 0

    if tool_name == "coolant_temperature_rise":
        if parse_mass_flow_kg_s(text) is not None or parse_volume_flow_m3_s(text) is not None or "kg/s" in lowered:
            score += 4
        if _has_any(lowered, ("冷却液温升", "温升是多少", "出入口温差", "出口温度", "coolant temperature rise")):
            score += 4
        if _has_any(lowered, ("带走", "带走 800w", "吸收")):
            score += 2

    elif tool_name == "conduction_resistance":
        if parse_thickness_m(text) is not None:
            score += 2
        if parse_conductivity_w_mk(text) is not None:
            score += 2
        if parse_area_m2(text) is not None:
            score += 2
        if _has_any(lowered, ("导热热阻", "导热系数", "厚度", "面积", "tim", "r_cond")):
            score += 3

    elif tool_name == "plane_wall_conduction":
        if parse_thickness_m(text) is not None:
            score += 2
        if parse_conductivity_w_mk(text) is not None:
            score += 2
        if parse_area_m2(text) is not None:
            score += 2
        if parse_plane_wall_temperature_difference_k(text) is not None:
            score += 3
        if _has_any(lowered, ("平壁", "稳态导热", "导热量", "热流量", "传热量", "两侧温度", "温度分别")):
            score += 5

    elif tool_name == "junction_temperature_estimate":
        if _has_any(lowered, ("结温", "junction temperature", "tj", "芯片温度")):
            score += 4
        if parse_thermal_resistance_k_per_w(text) is not None or "总热阻" in text or "k/w" in lowered:
            score += 3
        if _has_any(lowered, ("环境温度", "入口水温", "入口温度", "功耗")):
            score += 1

    elif tool_name == "required_thermal_resistance":
        if _has_any(lowered, ("所需热阻", "需要总热阻", "需要多低热阻", "总热阻小于", "热阻小于", "required thermal resistance")):
            score += 5
        if _has_any(lowered, ("最高结温", "结温限制", "不超过", "t_max", "t_limit")):
            score += 3
        if "热阻" in text and _has_any(lowered, ("需要", "小于", "多低", "多大")):
            score += 3

    elif tool_name == "liquid_flow_rate_required":
        if _has_any(lowered, ("l/min", "lpm", "升每分钟", "需要多少流量", "需要多大流量", "how many l/min")):
            score += 5
        if _has_any(lowered, ("允许温升", "温升不超过", "温差", "delta t", "allowed temperature rise", "δt", "螖t")):
            score += 3
        if _has_any(lowered, ("流量", "flow rate")):
            score += 2

    elif tool_name == "liquid_pressure_drop_estimate":
        if _has_any(lowered, ("压降", "压力损失", "pressure drop", "pressure loss", "delta p", "dp")):
            score += 7
        if _has_any(lowered, ("管径", "水力直径", "pipe diameter", "hydraulic diameter")):
            score += 3
        if _has_any(lowered, ("扬程", "pump head")):
            score += 3
        if _has_any(lowered, ("l/min", "lpm", "flow rate", "流量")):
            score += 1

    if tool_name == "liquid_network_flow_distribution":
        network_action = _has_any(lowered, ("flow distribution", "branch flow", "flow imbalance", "流量分配", "支路流量", "流量不均"))
        topology_signal = _has_any(lowered, ("parallel", "series", "并联", "串联"))
        resistance_signal = _has_any(lowered, ("branch resistance", "resistance coefficient", "支路阻力", "阻力系数"))
        if network_action:
            score += 8
        if topology_signal and (network_action or resistance_signal):
            score += 4
        if resistance_signal:
            score += 3

    if tool_name == "thermal_resistance_network_solve":
        network_signal = _has_any(lowered, ("thermal resistance network", "thermal path", "热阻网络", "热路径"))
        topology_signal = _has_any(lowered, ("series thermal resistance", "parallel thermal resistance", "串联热阻", "并联热阻"))
        analysis_signal = _has_any(lowered, ("thermal bottleneck", "thermal sensitivity", "瓶颈", "敏感性", "what-if"))
        numeric_resistance = bool(re.search(r"\d+(?:\.\d+)?\s*K/W", text, re.IGNORECASE))
        if network_signal and (_explicit_calculation_signal(text) or numeric_resistance or analysis_signal):
            score += 8
        if topology_signal and numeric_resistance:
            score += 9
        if analysis_signal and _has_any(lowered, ("热阻", "tim", "junction", "结温")):
            score += 7

    return score


def rank_candidate_tools(
    query: str,
    task: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> list[dict[str, Any]]:
    """Rank possible ToolSpec-backed calculation tools without executing them."""

    active_registry = registry or DEFAULT_TOOL_REGISTRY
    task_data = _task_to_dict(task)
    text = normalize_text(query or "")
    if not text or _hard_blocked(text, task_data):
        return []

    task_candidate = _candidate_from_task(task_data, active_registry)
    rows: list[dict[str, Any]] = []
    for spec in active_registry.list():
        if spec.domain not in {"thermal_management", "hydraulics", "thermal_network"}:
            continue
        score = _rule_score(spec.name, text)
        lowered = text.lower()
        for keyword in spec.intent_keywords:
            if keyword and keyword.lower() in lowered:
                score += 1
        if task_candidate == spec.name:
            score += 100
        if score > 0:
            rows.append({"tool_name": spec.name, "score": score, "domain": spec.domain})
    return sorted(rows, key=lambda item: (-int(item["score"]), str(item["tool_name"])))


def detect_calculation_tool(
    query: str,
    task: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> str | None:
    """Route a user query to a deterministic local calculation tool."""

    active_registry = registry or DEFAULT_TOOL_REGISTRY
    task_data = _task_to_dict(task)
    text = normalize_text(query or "")
    if not text or _hard_blocked(text, task_data):
        return None

    task_candidate = _candidate_from_task(task_data, active_registry)
    if task_candidate:
        return task_candidate

    ranked = rank_candidate_tools(text, task_data, active_registry)
    if not ranked:
        return None
    top = ranked[0]
    if int(top["score"]) < 3:
        return None
    return str(top["tool_name"])


def detect_property_lookup_tool(
    query: str,
    task: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> str | None:
    """Route coolant-property lookup questions without executing a tool."""

    active_registry = registry or DEFAULT_TOOL_REGISTRY
    if active_registry.get(PROPERTY_LOOKUP_TOOL_NAME) is None:
        return None
    task_data = _task_to_dict(task)
    task_type = str(task_data.get("task_type") or "")
    if bool(task_data.get("is_property_lookup")) or task_type == "property_lookup":
        return PROPERTY_LOOKUP_TOOL_NAME

    text = normalize_text(query or "")
    if not text:
        return None
    if _is_standards_or_range_lookup(text):
        return None
    if detect_fluid(text) is not None and detect_property_name(text) is not None:
        return PROPERTY_LOOKUP_TOOL_NAME
    return None


__all__ = ["detect_calculation_tool", "detect_property_lookup_tool", "rank_candidate_tools"]
