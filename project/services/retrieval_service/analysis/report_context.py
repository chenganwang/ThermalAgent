from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..tools.specs import TOOL_SPECS


@dataclass(frozen=True)
class KnownInput:
    name: str
    value: str
    source: str = "query"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MissingParameter:
    name: str
    reason: str
    required_for: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class CalculationSuggestion:
    title: str
    formula: str
    result_text: str
    assumptions: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceInsight:
    title: str
    engineering_point: str
    citation_hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class EngineeringReportContext:
    original_query: str
    report_subject: str
    known_inputs: list[KnownInput] = field(default_factory=list)
    missing_parameters: list[MissingParameter] = field(default_factory=list)
    cooling_path: list[str] = field(default_factory=list)
    calculation_suggestions: list[CalculationSuggestion] = field(default_factory=list)
    source_insights: list[SourceInsight] = field(default_factory=list)
    risk_items: list[str] = field(default_factory=list)
    validation_suggestions: list[str] = field(default_factory=list)
    next_data_needs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "report_subject": self.report_subject,
            "known_inputs": [item.to_dict() for item in self.known_inputs],
            "missing_parameters": [item.to_dict() for item in self.missing_parameters],
            "cooling_path": list(self.cooling_path),
            "calculation_suggestions": [item.to_dict() for item in self.calculation_suggestions],
            "source_insights": [item.to_dict() for item in self.source_insights],
            "risk_items": list(self.risk_items),
            "validation_suggestions": list(self.validation_suggestions),
            "next_data_needs": list(self.next_data_needs),
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
        }


_POWER_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kw|kW|KW|w|W|瓦|千瓦)")

_DEFAULT_MISSING_PARAMETERS = [
    MissingParameter("允许冷却液温升 ΔT", "缺少温升时不能给出唯一最终流量。", "流量估算和出口温度校核"),
    MissingParameter("冷却液类型及比热容 cp", "不同冷却液和浓度的物性差异会显著影响流量。", "能量守恒流量估算"),
    MissingParameter("入口水温", "入口温度决定芯片温度裕度和设施侧匹配。", "结温/壳温校核"),
    MissingParameter("目标结温或壳温上限", "缺少温度上限时无法判断方案裕度。", "可靠性判断"),
    MissingParameter("冷板热阻", "冷板热阻决定芯片到冷却液的温差。", "热阻网络校核"),
    MissingParameter("压降限制", "压降决定泵选型和支路分配风险。", "泵和管路匹配"),
    MissingParameter("泵曲线", "没有泵曲线不能确认目标流量是否可实现。", "系统级流量验证"),
]

_DEFAULT_RISKS = [
    "冷板压降过高，导致泵功耗、噪声或目标流量无法满足。",
    "TIM 接触热阻偏大，导致 GPU 结温或壳温裕度不足。",
    "实际流量不足或支路分配不均，导致局部热点。",
    "CDU / 换热器能力不足，导致供回液温度失控。",
    "接头、管路、冷却液污染带来的泄漏、堵塞和维护复杂度。",
]

_DEFAULT_VALIDATION = [
    "补充入口水温和允许冷却液温升 ΔT。",
    "确定 GPU 目标结温或壳温上限。",
    "查询冷板热阻、流阻和压降曲线。",
    "建立简化热阻网络并校核芯片到冷却液的温差。",
    "使用 CFD 或实验数据校核温度分布和压降，但当前报告不输出仿真结果。",
]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _source_title(source: Mapping[str, Any], idx: int) -> str:
    return str(source.get("title") or source.get("doc_title") or source.get("filename") or f"source_{idx}")


def _source_hint(source: Mapping[str, Any]) -> str:
    page_start = source.get("page_start")
    page_end = source.get("page_end")
    page = source.get("page")
    chunk_type = source.get("chunk_type") or source.get("type")
    parts: list[str] = []
    if page_start not in (None, "") and page_end not in (None, ""):
        parts.append(f"pages {page_start}-{page_end}" if page_start != page_end else f"page {page_start}")
    elif page not in (None, ""):
        parts.append(f"page {page}")
    if chunk_type:
        parts.append(f"chunk_type={chunk_type}")
    return ", ".join(parts)


def _source_text_for_classification(source: Mapping[str, Any]) -> str:
    fields = (
        source.get("title"),
        source.get("doc_title"),
        source.get("filename"),
        source.get("text_preview"),
        source.get("preview"),
        source.get("summary"),
    )
    return " ".join(str(item or "") for item in fields).lower()


def _build_source_insights(sources: list[dict[str, Any]]) -> list[SourceInsight]:
    insights: list[SourceInsight] = []
    for idx, source in enumerate(sources[:5], start=1):
        if not isinstance(source, Mapping):
            continue
        text = _source_text_for_classification(source)
        title = _source_title(source, idx)
        if any(term in text for term in ("ocp", "cold plate", "冷板", "liquid cooling", "液冷")):
            point = "该来源可作为冷板液冷设计背景依据，工程上需要关注流道、制造、装配、测试和可靠性验证。"
        elif any(term in text for term in ("data center", "server", "gpu", "ai", "数据中心", "服务器")):
            point = "该来源支持高功率密度设备需要从系统供冷、服务器集成和运维角度综合评估散热方案。"
        elif any(term in text for term in ("ashrae", "facility", "supply temperature", "供水温度")):
            point = "该来源可用于设施侧温度范围和供冷边界的背景约束，但仍需结合 GPU 温度上限校核。"
        else:
            point = "该来源可作为热管理背景依据，仍需要与本项目的热负荷、温升、冷板和泵选型参数结合校核。"
        insights.append(SourceInsight(title=title, engineering_point=point, citation_hint=_source_hint(source)))
    return insights


def _extract_power(query: str) -> tuple[float, str] | None:
    for match in _POWER_RE.finditer(query or ""):
        # A conductivity or heat-flux unit is not an independently supplied load.
        suffix = (query or "")[match.end():]
        if re.match(r"\s*(?:[/／·⋅*(（]|\.\s*m|m\s*(?:\^?[-−]1|⁻¹))|[A-Za-z0-9⁻²³^-]", suffix):
            continue
        value = float(match.group("value"))
        unit = match.group("unit").lower()
        watts = value * 1000.0 if unit in {"kw", "千瓦"} else value
        display = f"{watts:.0f} W" if watts.is_integer() else f"{watts:.3g} W"
        return watts, display
    return None


def _calculation_known_inputs(calculation: Mapping[str, Any]) -> list[KnownInput]:
    """Read normalized values and their declared units, without recalculating."""
    tool_name = str(calculation.get("tool_name") or "")
    spec = TOOL_SPECS.get(tool_name)
    inputs = calculation.get("tool_inputs") or {}
    if spec is None or not isinstance(inputs, Mapping):
        return []
    result = []
    for name, value in inputs.items():
        if value is None:
            continue
        display = f"{value:.6g}" if isinstance(value, float) else str(value)
        result.append(KnownInput(name, f"{display} {spec.units.get(name, '')}".strip(), f"calculation:{tool_name}"))
    return result


def _plane_wall_context(query: str, sources: list[dict[str, Any]], calculation: Mapping[str, Any]) -> EngineeringReportContext:
    missing = [
        MissingParameter(str(name), "当前计算尚未获得此必需参数。", "一维平壁稳态导热计算")
        for name in calculation.get("missing_parameters") or []
    ]
    warnings = [] if sources else ["当前报告缺少检索来源支撑；需核对材料数据和公式适用范围。"]
    if calculation.get("tool_status") not in {"ok", "success"}:
        warnings.append("确定性计算尚未成功，报告不将未通过校验的数值作为有效结果。")
    return EngineeringReportContext(
        original_query=query,
        report_subject="平壁稳态导热工程报告",
        known_inputs=_calculation_known_inputs(calculation),
        missing_parameters=missing,
        cooling_path=["高温侧边界", "均匀平壁导热层", "低温侧边界"],
        source_insights=[SourceInsight(
            title=_source_title(source, index),
            engineering_point="检索片段用于人工核对导热公式、材料参数和适用条件；计算结果来自所列确定性工具，来源本身不是计算验证。",
            citation_hint=_source_hint(source),
        ) for index, source in enumerate(sources[:5], start=1)],
        risk_items=["材料导热系数随温度变化、接触热阻、边缘散热或内部发热会使一维估算偏离实际工况。"],
        validation_suggestions=[
            "核对厚度、导热面积、两侧温差及材料导热系数的单位和来源。",
            "确认稳态、一维和均匀材料假设；必要时用独立实验或已验证数值模型比对。",
        ],
        next_data_needs=[item.name for item in missing],
        assumptions=["一维稳态导热、恒定导热系数、均匀截面积、无内部热源，忽略接触热阻和边缘效应。"],
        warnings=warnings,
    )


def _has_gpu(query: str) -> bool:
    lowered = (query or "").lower()
    return "gpu" in lowered or "图形处理器" in query


def _has_cold_plate(query: str) -> bool:
    lowered = (query or "").lower()
    return "cold plate" in lowered or "冷板" in query


def _has_liquid_cooling(query: str) -> bool:
    lowered = (query or "").lower()
    return "liquid cooling" in lowered or "liquid-cooling" in lowered or "液冷" in query


def _build_known_inputs(query: str) -> list[KnownInput]:
    inputs: list[KnownInput] = []
    power = _extract_power(query)
    if power:
        inputs.append(KnownInput("热负荷", power[1]))
    if _has_gpu(query):
        inputs.append(KnownInput("热源对象", "GPU"))
    if _has_cold_plate(query) and _has_liquid_cooling(query):
        inputs.append(KnownInput("冷却方式", "冷板液冷"))
    elif _has_cold_plate(query):
        inputs.append(KnownInput("冷却部件", "冷板"))
    elif _has_liquid_cooling(query):
        inputs.append(KnownInput("冷却方式", "液冷"))
    return inputs


def _build_report_subject(query: str, known_inputs: list[KnownInput]) -> str:
    values = {item.name: item.value for item in known_inputs}
    if values.get("热负荷") and values.get("热源对象") == "GPU" and "冷板液冷" in values.values():
        return f"{values['热负荷'].replace(' ', '')} GPU 冷板液冷散热方案分析报告"
    if values.get("热负荷") and "冷板液冷" in values.values():
        return f"{values['热负荷'].replace(' ', '')} 冷板液冷散热方案分析报告"
    if "冷板液冷" in values.values():
        return "冷板液冷散热方案分析报告"
    if not (query or "").strip():
        return "液冷散热分析报告（缺少问题描述）"
    return "液冷散热分析报告"


def _build_cooling_path(query: str) -> list[str]:
    if _has_gpu(query) or _has_cold_plate(query) or _has_liquid_cooling(query):
        return ["GPU", "TIM", "冷板底板", "冷板内部流道", "冷却液", "CDU / 换热器", "设施水系统或环境"]
    return ["芯片/热源", "TIM", "冷板", "冷却液", "CDU / 换热器", "外部冷源"]


def _build_calculation_suggestions(query: str) -> tuple[list[CalculationSuggestion], list[str]]:
    power = _extract_power(query)
    assumptions: list[str] = []
    suggestions: list[CalculationSuggestion] = []
    if not power:
        return suggestions, assumptions

    watts, display = power
    if not (_has_cold_plate(query) or _has_liquid_cooling(query)):
        return suggestions, assumptions

    cp = 4180.0
    delta_t = 5.0
    rho = 1000.0
    mass_flow = watts / (cp * delta_t)
    volume_flow_l_min = mass_flow / rho * 1000.0 * 60.0
    assumptions = [
        "示例估算假设冷却液为水，cp≈4180 J/(kg·K)。",
        "示例估算假设允许冷却液温升 ΔT=5K。",
        "示例估算假设水密度约 1000 kg/m³。",
        "该结果仅为一级估算，不替代最终设计、CFD 或实验验证。",
    ]
    result = (
        f"在仅已知热负荷 {display} 且缺少 ΔT、冷却液物性和压降曲线时，不能给出唯一最终设计流量。"
        f"若仅作水冷一级示例估算：m_dot ≈ {watts:.0f} / (4180 × 5) ≈ {mass_flow:.4f} kg/s，"
        f"体积流量约 {volume_flow_l_min:.2f} L/min。"
    )
    suggestions.append(
        CalculationSuggestion(
            title="一级流量估算示例",
            formula="m_dot = Q / (cp × ΔT)",
            result_text=result,
            assumptions=assumptions,
            missing_parameters=["允许冷却液温升 ΔT", "冷却液类型及比热容 cp", "冷板压降曲线", "泵曲线"],
        )
    )
    return suggestions, assumptions


def build_engineering_report_context(
    query: str,
    task: dict | None = None,
    sources: list[dict] | None = None,
    calculation_metadata: dict | None = None,
    analysis_metadata: dict | None = None,
) -> EngineeringReportContext:
    """Build an engineering-oriented context for Markdown report rendering.

    This function is pure rule-based context assembly. It does not call an LLM,
    retrieval, tools, databases, or exporters.
    """

    original_query = query or ""
    source_items = [item for item in (sources or []) if isinstance(item, dict)]
    calculation = dict(calculation_metadata or {})
    if calculation.get("tool_name") == "plane_wall_conduction":
        return _plane_wall_context(original_query, source_items, calculation)
    known_inputs = _build_known_inputs(original_query)
    known_inputs.extend(_calculation_known_inputs(calculation))
    calculation_suggestions, assumptions = _build_calculation_suggestions(original_query)
    warnings: list[str] = []
    if not original_query.strip():
        warnings.append("缺少明确问题描述，报告只能给出低置信度通用分析框架。")
    if not source_items:
        warnings.append("当前报告缺少检索来源支撑；应补充知识库来源、设计手册或厂商资料。")
    if not (_has_cold_plate(original_query) or _has_liquid_cooling(original_query)):
        warnings.append("未明确冷却方式；需要确认风冷、冷板液冷、浸没液冷或其他方案。")

    next_data_needs = _dedupe([item.name for item in _DEFAULT_MISSING_PARAMETERS])
    return EngineeringReportContext(
        original_query=original_query,
        report_subject=_build_report_subject(original_query, known_inputs),
        known_inputs=known_inputs,
        missing_parameters=list(_DEFAULT_MISSING_PARAMETERS),
        cooling_path=_build_cooling_path(original_query),
        calculation_suggestions=calculation_suggestions,
        source_insights=_build_source_insights(source_items),
        risk_items=list(_DEFAULT_RISKS),
        validation_suggestions=list(_DEFAULT_VALIDATION),
        next_data_needs=next_data_needs,
        assumptions=assumptions,
        warnings=warnings,
    )


__all__ = [
    "CalculationSuggestion",
    "EngineeringReportContext",
    "KnownInput",
    "MissingParameter",
    "SourceInsight",
    "build_engineering_report_context",
]
