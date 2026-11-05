from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class SolutionSummary:
    generated: bool
    solution_type: str = ""
    title: str = ""
    input_conditions: list[dict[str, Any]] = field(default_factory=list)
    calculation_summary: list[dict[str, Any]] = field(default_factory=list)
    knowledge_basis: list[dict[str, Any]] = field(default_factory=list)
    recommended_thermal_path: list[str] = field(default_factory=list)
    visualization_refs: list[dict[str, Any]] = field(default_factory=list)
    simulation_readiness_summary: dict[str, Any] = field(default_factory=dict)
    engineering_judgement: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    required_additional_data: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SOLUTION_TRIGGERS = (
    "初步方案",
    "完整方案",
    "方案总结",
    "设计建议",
    "工程建议",
    "完整建议",
    "分析报告",
    "机柜散热分析",
    "液冷散热方案",
    "散热方案",
)

_LIQUID_COOLING_TERMS = (
    "液冷",
    "冷板",
    "冷却液",
    "CDU",
    "流量",
    "温升",
    "机柜",
)

_INPUT_LABELS = {
    "Q_W": ("热负荷", "W"),
    "P_W": ("热负荷", "W"),
    "delta_T_K": ("允许温升", "K"),
    "T_in_C": ("入口温度", "degC"),
    "T_max_C": ("最高允许温度", "degC"),
    "T_limit_C": ("温度限制", "degC"),
    "cp_J_kgK": ("比热容", "J/(kg*K)"),
    "rho_kg_m3": ("密度", "kg/m3"),
    "m_dot_kg_s": ("质量流量", "kg/s"),
    "R_total_K_per_W": ("总热阻", "K/W"),
    "fluid_name": ("冷却液类型", ""),
}


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    return {}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _should_generate(query: str, analysis_mode: Mapping[str, Any] | None) -> bool:
    mode = _as_mapping(analysis_mode)
    requested = {str(item) for item in mode.get("requested_outputs") or []}
    text = query or ""
    if bool(mode.get("enabled")):
        return True
    if requested.intersection({"solution", "solution_summary"}):
        return True
    return any(term in text for term in _SOLUTION_TRIGGERS)


def _is_liquid_solution(query: str, visualization_metadata: Mapping[str, Any], calculation_metadata: Mapping[str, Any]) -> bool:
    text = query or ""
    if any(term in text for term in _LIQUID_COOLING_TERMS):
        return True
    if str(calculation_metadata.get("tool_name") or "") in {"liquid_flow_rate_required", "coolant_temperature_rise"}:
        return True
    graph_type = str(visualization_metadata.get("graph_type") or "")
    return graph_type in {"thermal_path", "liquid_loop", "rack_liquid_cooling_path"}


def _format_value(value: Any, unit: str) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        text = f"{value:.6g}"
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def _condition(name: str, value: str, source: str) -> dict[str, str]:
    return {"name": name, "value": value, "source": source}


def _extract_input_conditions(query: str, task_result: Any, calculation_metadata: Mapping[str, Any]) -> list[dict[str, str]]:
    conditions: list[dict[str, str]] = []
    inputs = _as_mapping(calculation_metadata.get("tool_inputs"))
    if not inputs:
        raw = _as_mapping(calculation_metadata.get("raw"))
        inputs = _as_mapping(raw.get("inputs"))

    for key, value in inputs.items():
        if value in (None, "", [], {}):
            continue
        label, unit = _INPUT_LABELS.get(str(key), (str(key), ""))
        conditions.append(_condition(label, _format_value(value, unit), "calculation_metadata.tool_inputs"))

    text = query or ""
    if not any(item.get("name") == "热负荷" for item in conditions):
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kW|KW|kw|W|w)\b", text)
        if match:
            value = f"{match.group(1)} {match.group(2)}"
            conditions.append(_condition("热负荷", value, "query"))
    if not any(item.get("name") == "允许温升" for item in conditions) and re.search(r"(温升|温差|ΔT|delta\s*T|dT)", text, re.IGNORECASE):
        match = re.search(r"(\d+(?:\.\d+)?)\s*(K|℃|°C|C)\b", text, re.IGNORECASE)
        if match:
            conditions.append(_condition("允许温升", f"{match.group(1)} {match.group(2)}", "query"))
    if not any(item.get("name") == "冷却液类型" for item in conditions):
        if "冷却水" in text or "水" in text or "water" in text.lower():
            conditions.append(_condition("冷却液类型", "water", "query"))

    task = _as_mapping(task_result)
    for entity in task.get("entities") or []:
        name = str(entity).strip()
        if name and not any(item.get("value") == name for item in conditions):
            conditions.append(_condition("识别实体", name, "task_result.entities"))

    return conditions


def _summarize_result(tool_name: str, result: Mapping[str, Any]) -> str:
    if not result:
        return ""
    if tool_name == "liquid_flow_rate_required" and result.get("volume_flow_L_min") is not None:
        return f"所需体积流量约 {result.get('volume_flow_L_min')} L/min。"
    if tool_name == "coolant_temperature_rise" and result.get("delta_T_K") is not None:
        return f"冷却液温升约 {result.get('delta_T_K')} K。"
    if tool_name == "required_thermal_resistance" and result.get("R_required_K_per_W") is not None:
        return f"所需最大总热阻约 {result.get('R_required_K_per_W')} K/W。"
    if tool_name == "junction_temperature_estimate" and result.get("T_j_C") is not None:
        return f"估算结温约 {result.get('T_j_C')} degC。"
    if tool_name == "conduction_resistance" and result.get("R_cond_K_per_W") is not None:
        return f"一维导热热阻约 {result.get('R_cond_K_per_W')} K/W。"
    parts = [f"{key}={value}" for key, value in result.items() if value is not None]
    return "；".join(parts)


def _extract_calculation_summary(calculation_metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not bool(calculation_metadata.get("used_calculation")):
        return []
    if str(calculation_metadata.get("tool_status") or "") != "ok":
        return []
    result = _as_mapping(calculation_metadata.get("tool_result"))
    tool_name = str(calculation_metadata.get("tool_name") or "")
    return [
        {
            "tool_name": tool_name,
            "result_summary": _summarize_result(tool_name, result),
            "formula": calculation_metadata.get("tool_formula"),
            "result": result,
            "warnings": list(calculation_metadata.get("tool_warnings") or []),
            "assumptions": list(calculation_metadata.get("assumptions") or []),
        }
    ]


def _preview(text: Any, limit: int = 160) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


def _extract_knowledge_basis(sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    basis: list[dict[str, Any]] = []
    for source in list(sources or [])[:3]:
        if not isinstance(source, Mapping):
            continue
        basis.append(
            {
                "title": source.get("title") or source.get("book_title") or source.get("doc_title"),
                "page_start": source.get("page_start") or source.get("page"),
                "page_end": source.get("page_end") or source.get("page"),
                "chunk_type": source.get("chunk_type"),
                "text_preview": _preview(source.get("text_preview") or source.get("preview") or source.get("text")),
            }
        )
    return basis


def _extract_visualization_refs(visualization_metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not bool(visualization_metadata.get("generated")):
        return []
    graph = _as_mapping(visualization_metadata.get("graph"))
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    return [
        {
            "graph_type": visualization_metadata.get("graph_type") or graph.get("graph_type"),
            "node_count": len(nodes) if isinstance(nodes, list) else 0,
            "edge_count": len(edges) if isinstance(edges, list) else 0,
            "generic_template": bool(visualization_metadata.get("generic_template", graph.get("generic_template", True))),
            "source_based": bool(visualization_metadata.get("source_based", graph.get("source_based", False))),
        }
    ]


def _extract_thermal_path(query: str, visualization_metadata: Mapping[str, Any]) -> tuple[list[str], bool]:
    if bool(visualization_metadata.get("generated")):
        graph = _as_mapping(visualization_metadata.get("graph"))
        nodes = graph.get("nodes") or []
        labels = [str(node.get("label")) for node in nodes if isinstance(node, Mapping) and node.get("label")]
        if labels:
            return labels, bool(visualization_metadata.get("generic_template", graph.get("generic_template", True)))

    if any(term in (query or "") for term in _LIQUID_COOLING_TERMS):
        return ["芯片", "TIM", "冷板", "冷却液", "CDU", "外部冷源"], True
    return [], False


def _extract_simulation_summary(simulation_metadata: Mapping[str, Any]) -> dict[str, Any]:
    if not bool(simulation_metadata.get("enabled")):
        return {}
    readiness = _as_mapping(simulation_metadata.get("readiness"))
    model_file = _as_mapping(simulation_metadata.get("model_file") or readiness.get("model_file"))
    return {
        "simulation_ready": bool(simulation_metadata.get("simulation_ready", readiness.get("simulation_ready", False))),
        "missing_conditions": list(readiness.get("missing_conditions") or simulation_metadata.get("missing_conditions") or []),
        "next_action": readiness.get("next_action") or simulation_metadata.get("next_action"),
        "model_file": model_file,
    }


def _engineering_judgement(
    calculation_summary: list[dict[str, Any]],
    knowledge_basis: list[dict[str, Any]],
    simulation_summary: Mapping[str, Any],
) -> list[str]:
    judgement: list[str] = []
    if calculation_summary:
        judgement.append("当前计算结果可作为一级工程估算。")
    if knowledge_basis:
        judgement.append("当前方案摘要引用了已检索到的知识库来源，但仍需人工核对适用条件。")
    if simulation_summary and simulation_summary.get("simulation_ready") is False:
        judgement.append("当前仿真准备信息不足，不能输出仿真数值结果。")
    judgement.append("该方案仍需结合冷板压降、泵曲线和实际边界条件进一步确认。")
    judgement.append("当前结果不能替代 CFD 或详细结构设计。")
    return _dedupe(judgement)


def _risks(is_liquid: bool, simulation_summary: Mapping[str, Any]) -> list[str]:
    risks: list[str] = []
    if is_liquid:
        risks.extend(
            [
                "冷板压降未校核。",
                "泵曲线未匹配。",
                "接头和管路泄漏风险未评估。",
                "冷却液物性未完整确认。",
                "TIM 接触热阻未验证。",
                "机柜级风道或液冷支路分配未验证。",
            ]
        )
    missing = [str(item) for item in simulation_summary.get("missing_conditions") or []]
    if simulation_summary:
        risks.append("模型文件仅提供几何信息，缺少完整热源分布和边界条件时不能用于仿真结论。")
        risks.append("当前未进行网格划分和求解。")
    if "热源分布" in missing:
        risks.append("热源分布未补充，无法判断局部热点和机柜级负载分布。")
    return _dedupe(risks)


def _required_data(is_liquid: bool, simulation_summary: Mapping[str, Any]) -> list[str]:
    data = [
        "热源功率分布",
        "进水/进风温度",
        "冷却液类型和物性",
        "流量或泵曲线",
        "冷板压降",
        "材料导热系数",
        "服务器/机柜布局",
        "实测温度或仿真边界条件",
    ]
    for missing in simulation_summary.get("missing_conditions") or []:
        text = str(missing)
        if text and text not in data:
            data.insert(0, text)
    if not is_liquid:
        data = [item for item in data if item not in {"冷却液类型和物性", "流量或泵曲线", "冷板压降"}]
    return _dedupe(data)


def _next_steps(has_graph: bool, simulation_summary: Mapping[str, Any]) -> list[str]:
    steps = [
        "补充边界条件。",
        "校核流量和温升。",
        "检查冷板压降和泵匹配。",
        "进行实验或公开算例验证。",
    ]
    if not has_graph:
        steps.insert(2, "建立散热路径图。")
    if simulation_summary:
        steps.insert(-1, "补齐缺失工况后准备仿真任务。")
    return _dedupe(steps)


def _limitations(generic_path_used: bool) -> list[str]:
    items = [
        "当前为一级工程估算。",
        "不替代 CFD。",
        "不替代工业级冷板设计。",
        "不包含详细流道、压降和泵曲线。",
        "不编造缺失的物性或仿真数据。",
    ]
    if generic_path_used:
        items.append("推荐散热路径为 generic template，不是具体模型仿真结果。")
    return items


def build_solution_summary(
    query: str,
    task_result: object | None = None,
    sources: list[dict[str, Any]] | None = None,
    calculation_metadata: dict | None = None,
    knowledge_metadata: dict | None = None,
    visualization_metadata: dict | None = None,
    simulation_metadata: dict | None = None,
    analysis_mode: dict | None = None,
) -> dict[str, Any]:
    """Build a structured first-pass solution summary from existing metadata.

    This module is deterministic and does not call an LLM, run CFD, infer
    missing material properties, or invent source facts.
    """

    calculation = _as_mapping(calculation_metadata)
    visualization = _as_mapping(visualization_metadata)
    simulation = _as_mapping(simulation_metadata)
    mode = _as_mapping(analysis_mode)

    if not _should_generate(query, mode):
        return {"generated": False}

    liquid_solution = _is_liquid_solution(query, visualization, calculation)
    thermal_path, generic_path_used = _extract_thermal_path(query, visualization)
    calculation_summary = _extract_calculation_summary(calculation)
    knowledge_basis = _extract_knowledge_basis(sources)
    visualization_refs = _extract_visualization_refs(visualization)
    simulation_summary = _extract_simulation_summary(simulation)

    solution = SolutionSummary(
        generated=True,
        solution_type="liquid_cooling_initial_plan" if liquid_solution else "thermal_analysis_initial_plan",
        title="液冷散热初步方案摘要" if liquid_solution else "热管理初步分析摘要",
        input_conditions=_extract_input_conditions(query, task_result, calculation),
        calculation_summary=calculation_summary,
        knowledge_basis=knowledge_basis,
        recommended_thermal_path=thermal_path,
        visualization_refs=visualization_refs,
        simulation_readiness_summary=simulation_summary,
        engineering_judgement=_engineering_judgement(calculation_summary, knowledge_basis, simulation_summary),
        risks=_risks(liquid_solution, simulation_summary),
        required_additional_data=_required_data(liquid_solution, simulation_summary),
        next_steps=_next_steps(bool(visualization_refs), simulation_summary),
        limitations=_limitations(generic_path_used),
    )
    return solution.to_dict()


__all__ = ["SolutionSummary", "build_solution_summary"]
