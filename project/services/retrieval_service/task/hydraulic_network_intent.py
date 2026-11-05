from __future__ import annotations

import re
from typing import Any

from .normalizer import normalize_query
from .network_domain import detect_network_domain


NETWORK_TOOL = "liquid_network_flow_distribution"


def detect_hydraulic_network_intent(query: str) -> dict[str, Any]:
    normalized = normalize_query(query or "")
    empty = {
        "is_hydraulic_network": False,
        "flow_distribution_requested": False,
        "needs_calculation": False,
        "candidate_tools": [],
        "signals": [],
        "topology": "unknown",
        "branch_count": None,
        "identical_branches_explicit": False,
        "total_flow_present": False,
        "equal_split_ready": False,
    }
    if not normalized:
        return empty

    domain = detect_network_domain(normalized)
    if domain["domain"] != "hydraulic":
        return {**empty, "signals": [f"network_domain:{domain['domain']}"] if domain["topology_present"] else []}

    topology_value = (
        "parallel" if re.search(r"并联|parallel", normalized, re.IGNORECASE)
        else "series" if re.search(r"串联|series", normalized, re.IGNORECASE)
        else "unknown"
    )
    topology = topology_value != "unknown"
    network_object = bool(re.search(r"冷板|支路|流道|元件|回路|branch|cold\s*plate|component|loop", normalized, re.IGNORECASE))
    distribution = bool(re.search(r"分流|流量分配|每个多少|支路流量|不均|flow\s*distribution|branch\s*flow|imbalance", normalized, re.IGNORECASE))
    pressure_sum = bool(re.search(r"总压降|压降分别|pressure\s*drop.*(?:total|sum)|sum.*pressure\s*drop", normalized, re.IGNORECASE))
    preparation = bool(re.search(r"缺哪些参数|需要哪些参数|如何建模|准备清单|missing\s*(?:inputs|parameters)|what.*parameters", normalized, re.IGNORECASE))
    resistance = bool(re.search(r"阻力系数|支路阻力|resistance\s*(?:coefficient|exponent)?", normalized, re.IGNORECASE))
    explicit_identical = bool(
        re.search(
            r"完全相同|结构相同|相同支路|阻力特性(?:相同|一致)|等阻力|identical|same\s+(?:geometry|resistance)",
            normalized,
            re.IGNORECASE,
        )
    )
    chinese_counts = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}
    count_match = re.search(r"(?:(\d+)|([两二三四五六七八]))\s*(?:个|路)?(?:[^，。；;]{0,20})(?:并联|串联|parallel|series)", normalized, re.IGNORECASE)
    branch_count = (
        int(count_match.group(1)) if count_match and count_match.group(1)
        else chinese_counts.get(count_match.group(2)) if count_match else None
    )
    total_flow_present = bool(
        re.search(r"总流量\s*(?:为|=|:)?\s*\d+(?:\.\d+)?\s*(?:L/min|lpm|m3/s)|total\s+flow", normalized, re.IGNORECASE)
    )
    equal_split_ready = bool(
        topology_value == "parallel"
        and branch_count is not None
        and branch_count > 0
        and explicit_identical
        and total_flow_present
    )
    numerical = bool(re.search(r"\d", normalized))
    concept_only = bool(re.search(r"什么是|定义|解释.*原理|what\s+is|definition|explain", normalized, re.IGNORECASE)) and not any(
        (distribution, pressure_sum, preparation, resistance, explicit_identical, numerical)
    )
    property_only = bool(re.search(r"\b(?:cp|rho)\b|比热|密度|粘度|黏度|物性", normalized, re.IGNORECASE))

    requested = bool(
        topology
        and network_object
        and not concept_only
        and not property_only
        and any((distribution, pressure_sum, preparation, resistance, explicit_identical, numerical))
    )
    signals: list[str] = []
    if requested:
        signals.append("hydraulic_network")
    if distribution:
        signals.append("flow_distribution")
    if pressure_sum:
        signals.append("series_pressure_sum")
    if preparation:
        signals.append("network_preparation")
    if equal_split_ready:
        signals.append("equal_split_assumption_ready")
    return {
        "is_hydraulic_network": requested,
        "flow_distribution_requested": requested,
        "needs_calculation": requested,
        "candidate_tools": [NETWORK_TOOL] if requested else [],
        "signals": signals,
        "topology": topology_value,
        "branch_count": branch_count,
        "identical_branches_explicit": explicit_identical,
        "total_flow_present": total_flow_present,
        "equal_split_ready": equal_split_ready,
    }


__all__ = ["NETWORK_TOOL", "detect_hydraulic_network_intent"]
