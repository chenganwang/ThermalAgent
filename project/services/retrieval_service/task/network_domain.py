from __future__ import annotations

import re
from typing import Any

from .normalizer import normalize_query


_THERMAL_UNIT = re.compile(r"\bK\s*/\s*W\b|\bW\s*/\s*K\b", re.IGNORECASE)
_TEMPERATURE_UNIT = re.compile(r"[-+]?\d+(?:\.\d+)?\s*(?:K\b|℃|°C|degC\b)", re.IGNORECASE)
_HYDRAULIC_UNIT = re.compile(r"\b(?:Pa|kPa|MPa)\b|\bL\s*/\s*min\b|\blpm\b|\bkg\s*/\s*s\b", re.IGNORECASE)


def detect_network_domain(query: str) -> dict[str, Any]:
    """Classify network-domain evidence without selecting or executing a tool."""

    text = normalize_query(query or "")
    lowered = text.casefold()
    topology = bool(re.search(r"并联|串联|支路|分流|合流|parallel|series|branch|split|merge", text, re.IGNORECASE))
    thermal_signals: list[str] = []
    hydraulic_signals: list[str] = []

    if _THERMAL_UNIT.search(text):
        thermal_signals.append("thermal_resistance_unit")
    if len(_TEMPERATURE_UNIT.findall(text)) >= 1:
        thermal_signals.append("temperature_unit")
    if re.search(r"热阻|热网络|热流|导热|对流|温度边界|thermal\s+(?:resistance|network)|heat\s+flow|conduction|convection", text, re.IGNORECASE):
        thermal_signals.append("thermal_concept")

    if _HYDRAULIC_UNIT.search(text):
        hydraulic_signals.append("hydraulic_unit")
    if re.search(r"压降|压力损失|管路|管径|泵|扬程|流量分配|支路流量|pressure\s+drop|pipe|pump|flow\s+(?:rate|distribution)", text, re.IGNORECASE):
        hydraulic_signals.append("hydraulic_concept")
    elif "thermal_concept" not in thermal_signals and re.search(
        r"(?:冷板|冷却水|冷却液|流道).{0,24}分流|分流.{0,24}(?:冷板|冷却水|冷却液|流道)", text
    ):
        # Topology alone is ambiguous. A fluid component plus flow splitting is
        # enough to request hydraulic inputs; explicit heat-flow splitting is not.
        hydraulic_signals.append("hydraulic_concept")

    thermal_score = (4 if "thermal_resistance_unit" in thermal_signals else 0) + (
        3 if "temperature_unit" in thermal_signals else 0
    ) + (3 if "thermal_concept" in thermal_signals else 0)
    hydraulic_score = (4 if "hydraulic_unit" in hydraulic_signals else 0) + (
        4 if "hydraulic_concept" in hydraulic_signals else 0
    )
    if thermal_score and thermal_score > hydraulic_score:
        domain = "thermal"
    elif hydraulic_score and hydraulic_score > thermal_score:
        domain = "hydraulic"
    elif topology and not thermal_score and not hydraulic_score:
        domain = "ambiguous"
    elif thermal_score or hydraulic_score:
        domain = "ambiguous"
    else:
        domain = "unknown"

    model_action = bool(
        re.search(
            r"建立|创建|生成|建模|模型计划|build|create|generate|model(?:ing)?\s+plan",
            lowered,
            re.IGNORECASE,
        )
        and re.search(r"模型|热网络|仿真|模拟|model|thermal\s+network|simulation", lowered, re.IGNORECASE)
    )
    no_execute = bool(re.search(r"不要(?:立即)?执行|不执行|仅.*计划|只.*计划|do\s+not\s+(?:run|execute)|plan\s+only", lowered, re.IGNORECASE))
    simulate_action = bool(re.search(r"仿真|模拟|simulate|simulation|run\s+(?:the\s+)?model", lowered, re.IGNORECASE))
    calculate_action = bool(re.search(r"计算|估算|求|总.*多少|calculate|estimate|solve", lowered, re.IGNORECASE))
    explain_action = bool(re.search(r"解释|原理|怎么算|how\s+does|explain", lowered, re.IGNORECASE))
    if model_action or (simulate_action and no_execute):
        action = "plan"
    elif simulate_action:
        action = "simulate"
    elif calculate_action:
        action = "calculate"
    elif explain_action:
        action = "explain"
    else:
        action = "unspecified"
    return {
        "domain": domain,
        "action": action,
        "topology_present": topology,
        "thermal_signals": thermal_signals,
        "hydraulic_signals": hydraulic_signals,
        "thermal_score": thermal_score,
        "hydraulic_score": hydraulic_score,
        "no_execute": no_execute,
    }


__all__ = ["detect_network_domain"]
