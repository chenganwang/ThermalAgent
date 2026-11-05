from __future__ import annotations

import re
from typing import Any

from .normalizer import has_any, normalize_query


_REPORT_TERMS = (
    "分析报告",
    "报告",
    "生成报告",
    "markdown report",
    "engineering report",
)

_COMPARISON_TERMS = (
    "比较",
    "对比",
    "方案对比",
    "优缺点",
    "适用场景",
    "哪个好",
    "怎么选",
    "compare",
    "comparison",
    "versus",
    " vs ",
)

_SIMULATION_TERMS = (
    "仿真准备",
    "仿真准备检查",
    "simulation readiness",
    "simulation preparation",
    "CFD 前置检查",
    "CFD前置检查",
    "CFD readiness",
    "solver readiness",
    "边界条件",
    "网格",
    "step",
    "stp",
    "cabinet_model.step",
    "模型文件",
)


def detect_analysis_intent(query: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect report/comparison/simulation-preparation flags."""

    normalized = normalize_query(query)
    lowered = f" {normalized.lower()} "
    options = options or {}

    needs_report = has_any(normalized, _REPORT_TERMS) or bool(options.get("needs_report"))
    needs_comparison = has_any(normalized, _COMPARISON_TERMS) or bool(options.get("needs_comparison"))
    needs_simulation = (
        has_any(normalized, _SIMULATION_TERMS)
        or bool(
            re.search(
                r"\b(?:cfd|fluent|comsol)\b.{0,24}(?:前置检查|准备|readiness|preparation)",
                normalized,
                re.IGNORECASE,
            )
        )
        or bool(re.search(r"\.(?:step|stp)\b", lowered, re.IGNORECASE))
        or bool(options.get("needs_simulation"))
    )

    signals: list[str] = []
    if needs_report:
        signals.append("report")
    if needs_comparison:
        signals.append("comparison")
    if needs_simulation:
        signals.append("simulation_preparation")

    return {
        "needs_report": needs_report,
        "needs_comparison": needs_comparison,
        "needs_simulation": needs_simulation,
        "signals": signals,
    }
