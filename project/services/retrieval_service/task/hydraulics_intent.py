from __future__ import annotations

import re
from typing import Any

from .normalizer import normalize_query


PRESSURE_DROP_TOOL = "liquid_pressure_drop_estimate"


def detect_hydraulics_intent(query: str) -> dict[str, Any]:
    """Detect pressure-drop estimates and pump-selection preparation requests."""

    normalized = normalize_query(query)
    lowered = normalized.lower()
    if not normalized:
        return {
            "is_hydraulics": False,
            "pump_selection_requested": False,
            "needs_calculation": False,
            "candidate_tools": [],
            "signals": [],
        }

    concept_only = bool(
        re.search(r"(?:什么是|解释|定义|原理|what\s+is|explain|definition).{0,30}(?:压降|pressure\s+drop)", normalized, re.IGNORECASE)
    )
    pressure_term = bool(re.search(r"压降|压力损失|pressure\s+drop|pressure\s+loss|delta[_\s]*p|\bdp\b", normalized, re.IGNORECASE))
    estimate_signal = bool(
        re.search(r"估算|计算|求|多少|calculate|estimate|given|已知", normalized, re.IGNORECASE)
        or re.search(r"\d", normalized)
    )
    hydraulic_inputs = bool(
        re.search(r"水力直径|管径|流道|长度|L/min|lpm|kg/m3|Pa[·.*]?s|hydraulic\s+diameter|pipe\s+diameter", normalized, re.IGNORECASE)
    )
    pump_requested = bool(
        re.search(
            r"泵选型|选泵|泵.*扬程|扬程.*泵|泵曲线|泵型号|选型输入|vendor.{0,12}选型|"
            r"pump\s+selection|select\s+(?:a\s+)?pump|pump\s+head|pump\s+(?:curve|model)|vendor\s+selection|缺哪些参数",
            normalized,
            re.IGNORECASE,
        )
    )
    pressure_requested = pressure_term and not concept_only and (estimate_signal or hydraulic_inputs)
    selected = pressure_requested or pump_requested
    signals: list[str] = []
    if pressure_requested:
        signals.append("pressure_drop_estimate")
    if pump_requested:
        signals.append("pump_selection_preparation")
    return {
        "is_hydraulics": selected,
        "pump_selection_requested": pump_requested,
        "needs_calculation": selected,
        "candidate_tools": [PRESSURE_DROP_TOOL] if selected else [],
        "signals": signals,
    }


__all__ = ["PRESSURE_DROP_TOOL", "detect_hydraulics_intent"]
