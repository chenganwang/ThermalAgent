from __future__ import annotations

import re
from typing import Any

from .normalizer import normalize_query
from .network_domain import detect_network_domain
from .calculation_intent import is_formula_or_explanation_query


THERMAL_NETWORK_TOOL = "thermal_resistance_network_solve"


def detect_thermal_network_intent(query: str) -> dict[str, Any]:
    normalized = normalize_query(query or "")
    lowered = normalized.lower()
    empty = {
        "is_thermal_network": False,
        "thermal_network_requested": False,
        "bottleneck_requested": False,
        "sensitivity_requested": False,
        "needs_calculation": False,
        "candidate_tools": [],
        "signals": [],
    }
    if not normalized:
        return empty
    if is_formula_or_explanation_query(normalized):
        return empty
    domain = detect_network_domain(normalized)
    concept_only = bool(re.search(r"什么是|定义|what\s+is|definition", normalized, re.IGNORECASE))
    hydraulics = bool(re.search(r"压降|管径|水力直径|流量分配|支路流量|pressure\s+drop|hydraulic\s+diameter|flow\s+distribution", normalized, re.IGNORECASE))
    property_lookup = bool(re.search(r"\b(?:cp|rho)\b|比热|密度|粘度|黏度|冷却液物性", normalized, re.IGNORECASE))
    network_term = bool(re.search(r"(?:稳态)?热(?:阻)?网络|thermal(?:\s+resistance)?\s+network", normalized, re.IGNORECASE))
    topology = bool(re.search(r"串联热阻|并联热阻|series\s+thermal\s+resistance|parallel\s+thermal\s+resistance", normalized, re.IGNORECASE)) or bool(
        domain["domain"] == "thermal" and domain["topology_present"]
    )
    explicit_chain = len(re.findall(r"\d+(?:\.\d+)?\s*K/W", normalized, re.IGNORECASE)) >= 2 and bool(re.search(r"结温|junction|封装热阻|TIM|冷板", normalized, re.IGNORECASE))
    allowable = bool(
        re.search(
            r"(?:最大)?允许总热阻|热阻(?:网络)?余量|allowable\s+total\s+thermal\s+resistance|thermal\s+resistance\s+margin",
            normalized,
            re.IGNORECASE,
        )
    )
    bottleneck = bool(re.search(r"瓶颈|bottleneck", normalized, re.IGNORECASE)) and bool(re.search(r"热阻|热路径|thermal", normalized, re.IGNORECASE))
    legacy_path_visualization = bool(re.search(r"散热路径图|CDU", normalized, re.IGNORECASE))
    path = (
        bool(re.search(r"热路径|thermal\s+path", normalized, re.IGNORECASE))
        and bool(re.search(r"画|分析|缺|graph|draw|analy", normalized, re.IGNORECASE))
        and not legacy_path_visualization
    )
    sensitivity = bool(re.search(r"敏感性|影响怎么分析|what-if|提高到|降低\s*\d+\s*%|sensitivity", normalized, re.IGNORECASE)) and bool(re.search(r"TIM|热阻|导热率|换热系数|结温|thermal|junction", normalized, re.IGNORECASE))
    missing_chain = bool(
        re.search(r"封装.{0,24}TIM.{0,24}冷板|package.{0,24}TIM.{0,24}cold\s*plate", normalized, re.IGNORECASE)
        and re.search(r"未知|缺参|缺少|没有|missing|unknown", normalized, re.IGNORECASE)
        and re.search(r"结温|热阻|junction|thermal\s+resistance", normalized, re.IGNORECASE)
    )
    preparation = (
        network_term
        and bool(re.search(r"缺哪些参数|需要哪些参数|怎么分析|missing\s+(?:inputs|parameters)", normalized, re.IGNORECASE))
    ) or missing_chain
    network_diagram_only = (
        network_term
        and bool(re.search(r"示意图|展示|schematic|diagram", normalized, re.IGNORECASE))
        and not bool(re.search(r"\d+(?:\.\d+)?\s*K/W|结温|瓶颈|敏感性|what-if", normalized, re.IGNORECASE))
    )
    model_plan_requested = bool(domain["domain"] == "thermal" and domain["action"] in {"plan", "simulate"})
    requested = bool(
        not concept_only
        and not hydraulics
        and not property_lookup
        and not network_diagram_only
        and domain["domain"] != "hydraulic"
        and any((network_term, topology, explicit_chain, allowable, bottleneck, path, sensitivity, preparation, model_plan_requested))
    )
    if not requested:
        return empty
    signals = ["thermal_network"]
    if topology:
        signals.append("thermal_network_topology")
    if bottleneck:
        signals.append("thermal_bottleneck")
    if path:
        signals.append("thermal_path")
    if sensitivity:
        signals.append("thermal_sensitivity")
    if model_plan_requested:
        signals.append("thermal_model_plan")
    return {
        "is_thermal_network": True,
        "thermal_network_requested": True,
        "bottleneck_requested": bottleneck,
        "sensitivity_requested": sensitivity,
        "needs_calculation": not model_plan_requested,
        "candidate_tools": [] if model_plan_requested else [THERMAL_NETWORK_TOOL],
        "model_plan_requested": model_plan_requested,
        "signals": signals,
    }


__all__ = ["THERMAL_NETWORK_TOOL", "detect_thermal_network_intent"]
