from __future__ import annotations

import re
from typing import Any

from ..domain_rules import ashrae_rules
from .normalizer import normalize_query


_CALCULATION_KEYWORDS = (
    "计算",
    "估算",
    "代入",
    "热阻计算",
    "结温估算",
    "质量流量",
    "流量",
    "功率",
    "热阻",
    "导热量",
    "传热量",
    "温升",
    "calculate",
    "calculation",
    "estimate",
)

_TOOL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "liquid_flow_rate_required",
        (
            r"(流量需求|所需流量|需要多少|需要多大|多少).{0,28}(L/min|l/min|流量|质量流量)",
            r"(热负荷|功耗|发热量|热量).{0,40}(允许温升|温升|ΔT|delta\s*T).{0,40}(流量|L/min|l/min)",
            r"(允许温升|温升|ΔT|delta\s*T).{0,40}(热负荷|功耗|发热量|热量).{0,40}(流量|L/min|l/min)",
        ),
    ),
    (
        "junction_temperature_estimate",
        (
            r"(结温|芯片温度|热源温度).{0,24}(多少|是多少|估算|计算|求)",
            r"(环境温度|入口温度|冷却液温度).{0,50}(总热阻|热阻).{0,50}(结温|芯片温度)",
            r"(芯片功耗|功耗|热负荷).{0,50}(总热阻|热阻).{0,50}(结温|芯片温度)",
            r"(GPU|CPU|芯片).{0,60}(总热阻|热阻).{0,60}(估算|计算).{0,12}(芯片温度|结温|温度)",
            r"(总热阻|热阻).{0,50}(估算|计算).{0,12}(芯片温度|结温|温度)",
        ),
    ),
    (
        "required_thermal_resistance",
        (
            r"(需要多低|所需|最大允许|热阻目标).{0,18}(总热阻|热阻)",
            r"(允许结温|最高结温|目标结温).{0,50}(热阻|R)",
        ),
    ),
    (
        "conduction_resistance",
        (
            r"(导热热阻|导热垫|导热层|TIM).{0,28}(多少|计算|估算|求)",
            r"(厚度|导热系数|面积).{0,50}(导热热阻|热阻)",
        ),
    ),
    (
        "plane_wall_conduction",
        (
            r"(平壁|平板|壁).{0,50}(稳态导热|导热量|热流量|传热量).{0,28}(多少|计算|估算|求)?",
            r"(厚度|导热系数|面积).{0,80}(两侧温度|温度分别|温差).{0,50}(导热量|热流量|传热量|计算|估算|求)",
            r"(两侧温度|温度分别|温差).{0,80}(厚度|导热系数|面积).{0,50}(导热量|热流量|传热量|计算|估算|求)",
        ),
    ),
    (
        "coolant_temperature_rise",
        (
            r"(冷却液温升|温升多少|出口温度).{0,24}(多少|计算|估算|求)?",
            r"(流量|质量流量).{0,50}(带走|吸收).{0,18}(热量|热负荷|功耗)",
        ),
    ),
)

_LOOKUP_RANGE_PATTERNS = (
    r"(推荐|允许|规定|给出|对应|供水|干球|湿度|露点).*(温度|范围|等级|是多少)",
    r"(温度|范围|等级).*(推荐|允许|规定|对应|是多少)",
    r"\b(?:A1|A2|A3|A4|H1|W17|W27|W32|W40|W45|W\+)\b.*(?:是多少|range|recommended|allowable)",
    r"(recommended|allowable|dry[- ]?bulb|facility water supply|dew point|humidity).*(range|temperature|class)",
)

_FORMULA_OR_EXPLANATION_TERMS = (
    "公式",
    "物理意义",
    "怎么理解",
    "为什么",
    "为何",
    "哪些假设",
    "有什么假设",
    "关系",
    "解释",
    "说明",
    "原理",
    "explain",
    "why",
    "relationship",
)


def is_lookup_range_query(query: str) -> bool:
    """Return True for standards/table lookup phrasing, not calculations."""

    normalized = normalize_query(query)
    return ashrae_rules.is_lookup_range_query(normalized) or any(
        re.search(pattern, normalized, re.IGNORECASE) for pattern in _LOOKUP_RANGE_PATTERNS
    )


def is_formula_or_explanation_query(query: str) -> bool:
    normalized = normalize_query(query)
    # A flow/temperature curve is evaluated by the visualization workflow over
    # its range. Sending that range to the scalar tool invents a missing single
    # flow input. An explicitly separate numeric request still reaches tools.
    flow_temperature_plot = (
        bool(re.search(r"流量|mass\s+flow|flow\s+rate", normalized, re.IGNORECASE))
        and bool(re.search(r"温升|温差|temperature\s+rise|delta\s*t|ΔT", normalized, re.IGNORECASE))
        and bool(re.search(r"曲线|趋势|关系图|curve|plot|trend", normalized, re.IGNORECASE))
    )
    separate_calculation = bool(re.search(
        r"(?:另(?:行)?|同时|并且?).{0,4}(?:计算|估算|求解)|"
        r"(?:计算|估算|求解).{0,12}(?:单点|指定流量)|"
        r"(?:also|separately)\s+(?:calculate|estimate|solve)",
        normalized, re.IGNORECASE,
    ))
    if flow_temperature_plot and not separate_calculation:
        return True
    # A request to diagnose an observation is not a request to solve for an
    # unknown. Keep this guard shared by task understanding and tool routing;
    # their independent keyword scores otherwise turn "温差异常" into flow sizing.
    diagnostic = bool(re.search(
        r"异常|故障|过热|温度过高|不足|接触不良|局部热点|报警|排查|troubleshoot|overheat",
        normalized, re.IGNORECASE,
    ))
    numeric_request = bool(re.search(
        r"计算|估算|求解|帮我算|算一下|代入|calculate|estimate|solve|"
        r"(?:求|多少|多大).{0,15}(?:流量|温升|温差|热阻|结温|L/min|kg/s)|"
        r"(?:流量|温升|温差|热阻|结温|L/min|kg/s).{0,8}(?:多少|多大)",
        normalized, re.IGNORECASE,
    ))
    if diagnostic and not numeric_request:
        return True
    if not any(term in normalized.lower() for term in _FORMULA_OR_EXPLANATION_TERMS):
        return False
    return not bool(re.search(r"(求|帮我算|算一下|计算一下|代入|已知|given|并(?:且)?(?:计算|估算|求解)|同时(?:计算|估算)|(?:calculate|estimate|solve)\b)", normalized, re.IGNORECASE))


def _is_standards_range_lookup(query: str) -> bool:
    normalized = normalize_query(query)
    if not is_lookup_range_query(normalized):
        return False
    return bool(
        ashrae_rules.is_ashrae_query(normalized)
        or re.search(r"\bOCP\b|\bW(?:17|27|32|40|45|\+)\b|Open Compute Project", normalized, re.IGNORECASE)
    )


def detect_calculation_intent(query: str) -> dict[str, Any]:
    """Detect calculation need and candidate local tool names.

    This module only identifies intent. It does not import tool registry
    objects, execute tools, or modify formulas.
    """

    normalized = normalize_query(query)
    lowered = normalized.lower()
    if not normalized:
        return {"needs_calculation": False, "candidate_tools": [], "signals": ["empty_query"]}
    if is_formula_or_explanation_query(normalized):
        return {"needs_calculation": False, "candidate_tools": [], "signals": ["formula_or_explanation_exempt"]}

    explicit_known_calculation = bool(
        re.search(r"(已知|given).*(求|calculate|estimate)", normalized, re.IGNORECASE)
    )
    if _is_standards_range_lookup(normalized) and not explicit_known_calculation:
        return {"needs_calculation": False, "candidate_tools": [], "signals": ["standards_lookup_exempt"]}

    if is_lookup_range_query(normalized) and _is_standards_range_lookup(normalized) and not explicit_known_calculation:
        return {"needs_calculation": False, "candidate_tools": [], "signals": ["range_lookup_exempt"]}

    candidate_tools: list[str] = []
    matched_signals: list[str] = []
    for tool_name, patterns in _TOOL_PATTERNS:
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
            candidate_tools.append(tool_name)
            matched_signals.append(tool_name)

    explicit_calc = bool(
        re.search(r"(已知|given).*(求|计算|估算|calculate|estimate)", normalized, re.IGNORECASE)
        or re.search(r"(求|计算|估算).*(功率|热阻|导热量|传热量|热流量|流量|质量流量|温升|结温)", normalized)
        or any(
            keyword.lower() in lowered
            for keyword in _CALCULATION_KEYWORDS
            if keyword not in {"流量", "功率", "热阻", "温升"}
        )
    )

    needs_calculation = bool(candidate_tools or explicit_calc)
    if explicit_calc and "explicit_calculation_keyword" not in matched_signals:
        matched_signals.append("explicit_calculation_keyword")

    return {
        "needs_calculation": needs_calculation,
        "candidate_tools": candidate_tools,
        "signals": matched_signals,
    }


def is_calculation_request(query: str) -> bool:
    """Detect explicit engineering calculation intent.

    Standards lookup questions such as "recommended temperature range" or
    "A1 to A4 allowable dry-bulb temperature" are not calculations.
    """

    return bool(detect_calculation_intent(query).get("needs_calculation"))
