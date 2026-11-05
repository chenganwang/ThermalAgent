from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .report_context import EngineeringReportContext, build_engineering_report_context


_REPORT_TRIGGERS = (
    "生成报告",
    "输出报告",
    "分析报告",
    "整理成报告",
    "项目报告",
    "完整分析",
    "形成文档",
    "总结成 Markdown",
    "总结成Markdown",
    "markdown report",
    "markdown analysis report",
    "engineering report",
    "analysis report",
    "markdown报告",
)

_BOUNDARY_LIMITATIONS = [
    "当前为一级工程分析。",
    "不替代 CFD。",
    "不替代实验测试。",
    "不替代工业级冷板设计。",
    "未覆盖压降、泵曲线、冷板流道优化。",
    "不包含详细流道、压降、泵曲线。",
    "不编造缺失的物性、厂家数据或仿真结果。",
    "乙二醇/丙二醇物性需要物性表或厂商数据。",
    "需要进一步实验、仿真或现场数据验证。",
]

_GENERIC_NEXT_STEPS = [
    "补充芯片功耗、允许结温、入口温度、冷却液类型。",
    "补充冷板尺寸、流道结构。",
    "补充管路长度、泵曲线。",
    "校核流量、温升、冷板压降和泵匹配。",
    "如需 CFD，准备几何、材料、边界条件和网格设置。",
]


@dataclass(frozen=True)
class ReportBuildResult:
    generated: bool
    format: str = "markdown"
    title: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    source_count: int = 0
    includes: dict[str, bool] = field(default_factory=dict)
    exports: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, bool] = field(default_factory=dict)
    render_hints: dict[str, Any] = field(default_factory=dict)
    physics_validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        if isinstance(converted, Mapping):
            return converted
    return {}


def _requested_outputs(analysis_mode: Mapping[str, Any]) -> set[str]:
    raw = analysis_mode.get("requested_outputs") or []
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def _contains_report_trigger(query: str) -> bool:
    lowered = (query or "").lower()
    return any(term.lower() in lowered for term in _REPORT_TRIGGERS)


def _should_generate_report(query: str, analysis_mode: Mapping[str, Any]) -> bool:
    requested = _requested_outputs(analysis_mode)
    if requested.intersection({"report", "markdown_report"}):
        return True
    if _contains_report_trigger(query):
        return True
    return bool(analysis_mode.get("enabled")) and _contains_report_trigger(query)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_value(item) for item in value)
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {_format_value(val)}" for key, val in value.items())
    return str(value)


def _source_count(sources: list[dict[str, Any]]) -> int:
    return len([item for item in sources if isinstance(item, dict)])


def _build_sections() -> list[dict[str, Any]]:
    titles = [
        ("problem_overview", "问题概述"),
        ("known_inputs", "已知输入条件"),
        ("calculation_results", "工程计算结果"),
        ("thermal_path_graph", "散热路径与图结构"),
        ("solution_summary", "方案摘要"),
        ("comparison", "方案对比"),
        ("simulation_readiness", "仿真准备状态"),
        ("sources", "来源依据"),
        ("boundaries", "风险与边界"),
        ("next_steps", "下一步建议"),
    ]
    return [{"id": section_id, "title": title, "included": True} for section_id, title in titles]


def _report_quality() -> dict[str, bool]:
    return {
        "has_input_table": True,
        "has_calculation_section": True,
        "has_visualization_section": True,
        "has_source_section": True,
        "has_boundary_section": True,
        "frontend_ready": True,
    }


def _render_hints() -> dict[str, Any]:
    return {
        "preferred_renderer": "markdown",
        "contains_tables": True,
        "contains_warnings": True,
    }


def _includes(
    answer: str | None,
    calculation_metadata: Mapping[str, Any],
    knowledge_metadata: Mapping[str, Any],
    visualization_metadata: Mapping[str, Any],
    simulation_metadata: Mapping[str, Any],
    solution_metadata: Mapping[str, Any],
    comparison_metadata: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "calculation": bool(calculation_metadata.get("used_calculation")),
        "knowledge": bool(answer) or bool(knowledge_metadata.get("synthesized")),
        "visualization": bool(visualization_metadata.get("generated")),
        "simulation": bool(simulation_metadata.get("enabled")),
        "solution": bool(solution_metadata.get("generated")),
        "comparison": bool(comparison_metadata.get("generated")),
    }


def _collect_limitations(
    visualization_metadata: Mapping[str, Any],
    simulation_metadata: Mapping[str, Any],
    solution_metadata: Mapping[str, Any],
    comparison_metadata: Mapping[str, Any],
) -> list[str]:
    values = list(_BOUNDARY_LIMITATIONS)
    graph = _as_mapping(visualization_metadata.get("graph"))
    values.extend(str(item) for item in graph.get("warnings") or [])
    values.extend(str(item) for item in graph.get("limitations") or [])
    values.extend(str(item) for item in visualization_metadata.get("limitations") or [])
    readiness = _as_mapping(simulation_metadata.get("readiness"))
    values.extend(str(item) for item in readiness.get("warnings") or [])
    values.extend(str(item) for item in solution_metadata.get("limitations") or [])
    values.extend(str(item) for item in comparison_metadata.get("limitations") or [])
    return _dedupe(values)


def _collect_next_steps(
    simulation_metadata: Mapping[str, Any],
    solution_metadata: Mapping[str, Any],
    comparison_metadata: Mapping[str, Any],
) -> list[str]:
    values = [str(item) for item in solution_metadata.get("next_steps") or []]
    values.extend(f"补充/确认：{item}" for item in comparison_metadata.get("required_additional_data") or [])
    readiness = _as_mapping(simulation_metadata.get("readiness"))
    next_action = readiness.get("next_action")
    if next_action:
        values.append(str(next_action))
    if not values:
        values = list(_GENERIC_NEXT_STEPS)
    return _dedupe(values)


_INPUT_SYMBOLS = {
    "热负荷": "P",
    "功耗": "P",
    "允许温升": "ΔT",
    "入口温度": "T_in",
    "入口水温": "T_in",
    "最高允许温度": "T_max",
    "目标结温": "T_j,max",
    "冷却液类型": "-",
    "热源对象": "-",
    "冷却方式": "-",
    "冷却部件": "-",
    "识别实体": "-",
}


def _split_value_unit(raw_value: str) -> tuple[str, str]:
    text = str(raw_value or "").strip()
    if not text:
        return "-", "-"
    parts = text.split()
    if len(parts) >= 2 and any(ch.isdigit() for ch in parts[0]):
        return " ".join(parts[:-1]), parts[-1]
    return text, "-"


def _render_known_inputs(context: EngineeringReportContext) -> list[str]:
    lines = ["| 参数 | 符号 | 数值 | 单位 | 来源 |", "| --- | --- | ---: | --- | --- |"]
    if not context.known_inputs:
        lines.append("| 当前问题未提供明确数值参数 | - | - | - | user_query |")
        lines.append("")
        lines.append("当前问题未提供明确数值参数；后续需要补充热源功率、设备对象、冷却架构和边界条件。")
        return lines
    for item in context.known_inputs:
        value, unit = _split_value_unit(item.value)
        symbol = _INPUT_SYMBOLS.get(item.name, "-")
        lines.append(f"| {item.name} | {symbol} | {value} | {unit} | {item.source} |")
    return lines


def _render_missing_parameters(context: EngineeringReportContext) -> list[str]:
    if not context.missing_parameters:
        return ["当前工具所需参数已齐全；材料来源和模型适用假设仍需核实。"]
    lines = ["| 缺失参数 | 为什么需要 | 用于什么判断 |", "| --- | --- | --- |"]
    for item in context.missing_parameters:
        lines.append(f"| {item.name} | {item.reason} | {item.required_for} |")
    return lines


_RESULT_UNITS = {
    "heat_rate_W": "W", "heat_flux_W_m2": "W/m2", "R_cond_K_per_W": "K/W",
    "R_required_K_per_W": "K/W", "R_with_margin_K_per_W": "K/W",
    "delta_T_K": "K", "temperature_rise_K": "K", "allowed_delta_T_K": "K",
    "T_j_C": "degC", "T_out_C": "degC", "margin_to_limit_C": "K",
    "mass_flow_kg_s": "kg/s", "volume_flow_L_min": "L/min", "volume_flow_m3_s": "m3/s",
}


def _physics_validation(calculation: Mapping[str, Any]) -> dict[str, Any]:
    raw = _as_mapping(calculation.get("raw"))
    return dict(_as_mapping(calculation.get("physics_validation") or raw.get("physics_validation")))


def _render_physics_validation(calculation: Mapping[str, Any]) -> list[str]:
    validation = _physics_validation(calculation)
    lines = ["", "### 确定性物理校验"]
    if not validation:
        return lines + ["当前工具未提供共享物理校验记录；不能据此认定结果已通过物理验证。"]
    passed = validation.get("passed") is True and validation.get("status") == "passed"
    lines.extend([
        f"- 校验结论：{'通过' if passed else '未通过'}（{validation.get('status') or 'unknown'}）。",
        f"- 方法：{validation.get('validation_method') or 'unknown'}；校验器：{validation.get('validator_version') or 'unknown'}。",
        f"- 检查物理量数：{validation.get('checked_quantity_count', 0)}。",
        f"- 能量一致性检查：{'已执行' if validation.get('energy_balance_checked') else '未执行'}。",
    ])
    if validation.get("energy_relative_error") is not None:
        lines.append(f"- 能量相对偏差：{_format_value(validation['energy_relative_error'])}。")
    for issue in validation.get("issues") or []:
        if isinstance(issue, Mapping):
            lines.append(f"- {issue.get('code', 'PHYSICS_ISSUE')} / {issue.get('field', '')}：{issue.get('message', '')}")
    lines.append("- 该记录来自确定性约束检查，不依赖 LLM 自我判断；代数一致性不等于独立实验或仿真验证。")
    lines.extend(f"- {item}" for item in validation.get("limitations") or [])
    return lines


def _render_calculation(
    context: EngineeringReportContext,
    calculation_metadata: Mapping[str, Any],
) -> list[str]:
    used = bool(calculation_metadata.get("used_calculation"))
    status = str(calculation_metadata.get("tool_status") or "")
    lines: list[str] = []
    validation_failed = _physics_validation(calculation_metadata).get("passed") is False
    if used and status == "ok" and not validation_failed:
        tool_name = calculation_metadata.get("tool_name") or "unknown_tool"
        formula = calculation_metadata.get("tool_formula") or calculation_metadata.get("formula")
        result = calculation_metadata.get("tool_result") or calculation_metadata.get("result") or {}
        lines.append(f"- 确定性计算工具：{tool_name}")
        if formula:
            lines.append(f"- 公式：{formula}")
        if isinstance(result, Mapping) and result:
            lines.append("")
            lines.append("| 项目 | 结果 | 单位 |")
            lines.append("| --- | ---: | --- |")
            for key, value in result.items():
                display_value, display_unit = _split_value_unit(_format_value(value))
                display_unit = _RESULT_UNITS.get(str(key), display_unit)
                lines.append(f"| {key} | {display_value} | {display_unit} |")
        elif result:
            lines.append(f"- 结果：{_format_value(result)}")
        steps = calculation_metadata.get("tool_steps") or []
        if steps:
            lines.append("- 计算步骤：")
            for item in steps:
                lines.append(f"  - {item}")
        assumptions = calculation_metadata.get("assumptions") or []
        if assumptions:
            lines.append("- 工具假设：")
            for item in assumptions:
                lines.append(f"  - {item}")
        warnings = calculation_metadata.get("tool_warnings") or calculation_metadata.get("warnings") or []
        if warnings:
            lines.append("- 工具警告：")
            for item in warnings:
                lines.append(f"  - {item}")
        lines.extend(_render_physics_validation(calculation_metadata))
        return lines

    if calculation_metadata.get("tool_name") and status != "skipped":
        lines.extend([
            f"- 确定性计算工具：{calculation_metadata['tool_name']}",
            f"- 计算状态：{status or 'unknown'}；当前没有可采纳的确定性计算结果。",
        ])
        if calculation_metadata.get("tool_formula"):
            lines.append(f"- 公式：{calculation_metadata['tool_formula']}")
        if calculation_metadata.get("error"):
            lines.append(f"- 错误反馈：{calculation_metadata['error']}")
        if calculation_metadata.get("missing_parameters"):
            lines.append(f"- 缺失参数：{', '.join(map(str, calculation_metadata['missing_parameters']))}")
        lines.extend(_render_physics_validation(calculation_metadata))
        return lines

    lines.append("本次未触发确定性计算工具。")
    if context.calculation_suggestions:
        lines.append("以下仅为规则化一级估算示例，便于识别所需补充条件；它不是本地确定性工具结果。")
        for suggestion in context.calculation_suggestions:
            lines.append(f"### {suggestion.title}")
            lines.append(f"- 公式：{suggestion.formula}")
            lines.append(f"- 估算说明：{suggestion.result_text}")
            if suggestion.missing_parameters:
                lines.append("- 仍需补充：")
                for item in suggestion.missing_parameters:
                    lines.append(f"  - {item}")
            if suggestion.assumptions:
                lines.append("- 假设：")
                for item in suggestion.assumptions:
                    lines.append(f"  - {item}")
        return lines

    lines.extend(
        [
            "当前缺少可计算的热负荷、温升或冷却液物性参数，未给出确定性流量结果。",
            "后续应补充 Q、cp、ΔT、密度、冷板压降和泵曲线后再进行工具计算。",
        ]
    )
    return lines


def _source_pages(source: Mapping[str, Any]) -> str:
    page_start = source.get("page_start")
    page_end = source.get("page_end")
    if page_start not in (None, "") and page_end not in (None, ""):
        return str(page_start) if page_start == page_end else f"{page_start}-{page_end}"
    if page_start not in (None, ""):
        return str(page_start)
    page = source.get("page")
    return str(page) if page not in (None, "") else "-"


def _render_sources(context: EngineeringReportContext, sources: list[dict[str, Any]]) -> list[str]:
    if not sources:
        return ["本次未返回可用检索来源。本次未返回可用来源，相关结论应视为规则模板或一级估算结果，不能作为强来源结论。"]
    lines: list[str] = []
    lines.append("| title | chapter | page_start | page_end | text_preview |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for source in sources[:8]:
        if not isinstance(source, Mapping):
            continue
        title = source.get("title") or source.get("doc_title") or source.get("filename") or "-"
        chapter = source.get("chapter") or source.get("section") or "-"
        page_start = source.get("page_start") or source.get("page") or "-"
        page_end = source.get("page_end") or source.get("page") or "-"
        preview = " ".join(str(source.get("text_preview") or source.get("preview") or source.get("text") or "").split())[:220]
        lines.append(f"| {title} | {chapter} | {page_start} | {page_end} | {preview} |")
    for index, source in enumerate(sources[:8], start=1):
        identity = ", ".join(f"{key}={source[key]}" for key in ("doc_id", "document_id", "chunk_id") if source.get(key) is not None)
        if identity:
            lines.append(f"\n- 来源 {index} 追踪标识：{identity}。")
    if not context.source_insights:
        lines.append("")
        lines.append("已返回检索来源，但当前无法形成稳定的工程综合判断；建议人工核对来源标题、页码和段落类型。")
        return lines
    lines.append("")
    lines.append("### 检索依据与工程解释")
    for idx, insight in enumerate(context.source_insights, start=1):
        suffix = f"（{insight.citation_hint}）" if insight.citation_hint else ""
        lines.append(f"{idx}. {insight.title}{suffix}")
        lines.append(f"   - 工程解释：{insight.engineering_point}")
    return lines


def _render_visualization(visualization_metadata: Mapping[str, Any]) -> list[str]:
    if not visualization_metadata.get("generated"):
        return ["当前未提供 Graph JSON 图结构。"]
    graph = _as_mapping(visualization_metadata.get("graph"))
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    lines = [
        f"- graph_type：{visualization_metadata.get('graph_type') or graph.get('graph_type')}",
        f"- node_count：{len(nodes)}",
        f"- edge_count：{len(edges)}",
        "- 推荐散热路径："
    ]
    labels = [str(node.get("label") or node.get("id")) for node in nodes if isinstance(node, Mapping) and (node.get("label") or node.get("id"))]
    lines.append(f"  - {' -> '.join(labels)}" if labels else "  - 当前图结构未提供节点标签。")
    if nodes:
        lines.extend(["", "| 节点 | 类型 | 作用 | 主要风险 |", "| --- | --- | --- | --- |"])
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            risks = "；".join(str(item) for item in node.get("risks") or []) or "-"
            lines.append(f"| {node.get('label') or node.get('id')} | {node.get('type') or '-'} | {node.get('role') or node.get('description') or '-'} | {risks} |")
    if edges:
        lines.extend(["", "| 边 | 类型 | 方向 | 说明 | 主要风险 |", "| --- | --- | --- | --- | --- |"])
        for edge in edges:
            if not isinstance(edge, Mapping):
                continue
            edge_name = edge.get("label") or f"{edge.get('source')}->{edge.get('target')}"
            risks = "；".join(str(item) for item in edge.get("risks") or []) or "-"
            lines.append(f"| {edge_name} | {edge.get('type') or edge.get('mechanism') or '-'} | {edge.get('direction') or '-'} | {edge.get('description') or '-'} | {risks} |")
    warnings = graph.get("warnings") or []
    if warnings:
        lines.append("- 图结构边界：")
        for warning in warnings:
            lines.append(f"  - {warning}")
    limitations = visualization_metadata.get("limitations") or graph.get("limitations") or []
    if limitations:
        lines.append("- 图结构限制：")
        for limitation in limitations:
            lines.append(f"  - {limitation}")
    lines.append("- 本报告只引用 Graph JSON，不生成图片。")
    return lines


def _render_simulation(simulation_metadata: Mapping[str, Any]) -> list[str]:
    if not simulation_metadata.get("enabled"):
        return []
    readiness = _as_mapping(simulation_metadata.get("readiness"))
    model_file = _as_mapping(simulation_metadata.get("model_file") or readiness.get("model_file"))
    missing = readiness.get("missing_conditions") or []
    next_action = readiness.get("next_action") or simulation_metadata.get("next_action")
    lines = [f"- simulation_ready：{bool(simulation_metadata.get('simulation_ready'))}"]
    if model_file:
        lines.append(f"- model_file：{_format_value(model_file)}")
    if missing:
        lines.append("- missing_conditions：")
        for item in missing:
            lines.append(f"  - {item}")
    if next_action:
        lines.append(f"- next_action：{next_action}")
    lines.append("- 当前为仿真准备检查，不是 CFD 求解结果。")
    lines.append("- 当前仅为仿真准备 Stub，不运行 CFD，不输出仿真结果。")
    return lines


def _render_solution(solution_metadata: Mapping[str, Any]) -> list[str]:
    if not solution_metadata.get("generated"):
        return ["当前未请求方案摘要；如需方案卡片，可在 requested_outputs 中请求 solution。"]
    lines = ["本节为初步建议，需要进一步验证；不作为最终方案。"]
    for title, key in (
        ("engineering_judgement", "engineering_judgement"),
        ("risks", "risks"),
        ("required_additional_data", "required_additional_data"),
        ("next_steps", "next_steps"),
        ("limitations", "limitations"),
    ):
        values = solution_metadata.get(key) or []
        if not values:
            continue
        lines.append(f"- {title}：")
        for item in values:
            lines.append(f"  - {item}")
    return lines


def _render_comparison(comparison_metadata: Mapping[str, Any]) -> list[str]:
    if not comparison_metadata.get("generated"):
        return ["本次未请求方案对比。"]
    lines = [f"- comparison_type：{comparison_metadata.get('comparison_type')}"]
    options = comparison_metadata.get("options") or []
    if options:
        lines.append("- options：")
        for option in options:
            if isinstance(option, Mapping):
                lines.append(f"  - {option.get('name') or 'option'}：{option.get('summary') or ''}")
            else:
                lines.append(f"  - {option}")
    criteria = comparison_metadata.get("criteria") or []
    if criteria:
        lines.append("- criteria：")
        for criterion in criteria:
            if isinstance(criterion, Mapping):
                lines.append(
                    f"  - {criterion.get('name') or 'criterion'}：{criterion.get('description') or ''}"
                    f"（{criterion.get('weight_hint') or ''}）"
                )
            else:
                lines.append(f"  - {criterion}")
    recommendation = comparison_metadata.get("recommendation")
    if recommendation:
        lines.append(f"- recommendation：{recommendation}")
    return lines


def _render_content(
    context: EngineeringReportContext,
    query: str,
    sources: list[dict[str, Any]],
    calculation_metadata: Mapping[str, Any],
    visualization_metadata: Mapping[str, Any],
    simulation_metadata: Mapping[str, Any],
    solution_metadata: Mapping[str, Any],
    comparison_metadata: Mapping[str, Any],
    limitations: list[str],
    next_steps: list[str],
) -> str:
    plane_wall = calculation_metadata.get("tool_name") == "plane_wall_conduction"
    report_title = context.report_subject if plane_wall else "液冷散热分析报告"
    simulation_lines = _render_simulation(simulation_metadata) if simulation_metadata.get("enabled") else ["当前未请求仿真准备检查。"]
    blocks: list[list[str]] = [
        [
            f"# {report_title}",
            f"> 报告主题：{context.report_subject}",
            "## 1. 问题概述（问题描述与目标）",
            f"- 用户问题：{query or '(empty query)'}",
            "- 分析目标：整理已知输入、一级计算状态、散热路径、来源依据、方案摘要、风险边界和下一步补充条件。",
            "- 当前模式：analysis_report / markdown。",
            "本报告依据已执行的平壁导热工具，记录输入、公式、结果与校验证据。" if plane_wall else "本报告面向已知热负荷和冷板液冷场景，给出一级工程分析、缺失参数、散热路径、主要风险和验证建议。",
            "报告中的估算不替代独立仿真、实验测试或详细工程设计。" if plane_wall else "报告中的估算只用于方案初筛，不替代 CFD、实验测试或工业级冷板设计。",
        ],
        [
            "## 2. 已知输入条件",
            *_render_known_inputs(context),
            "",
            "### 缺失参数",
            *_render_missing_parameters(context),
        ],
        ["## 3. 工程计算结果", *_render_calculation(context, calculation_metadata)],
        [
            "## 4. 散热路径与图结构（推荐散热路径）",
            f"- 推荐散热路径：{' -> '.join(context.cooling_path)}",
            *(["以上为一维导热模型的传热路径，不代表真实几何或求解网格。"] if plane_wall else _render_visualization(visualization_metadata)),
        ],
        ["## 5. 方案摘要", *(["本次按已给定平壁参数进行计算；未执行结构优化或设备选型。"] if plane_wall else _render_solution(solution_metadata))],
        ["## 6. 方案对比", *_render_comparison(comparison_metadata)],
        ["## 7. 仿真准备状态", *simulation_lines],
        ["## 8. 来源依据（检索依据与工程解释）", *_render_sources(context, sources)],
        [
            "## 9. 风险与边界",
            "### 主要风险",
            *(f"- {item}" for item in context.risk_items),
            "### 边界说明",
            *(f"- {item}" for item in limitations),
        ],
        [
            "## 10. 下一步建议",
            "### 验证建议",
            *(f"- {item}" for item in context.validation_suggestions),
            "### 下一步数据需求",
            *(f"- {item}" for item in _dedupe(context.next_data_needs + next_steps)),
        ],
    ]

    if context.warnings:
        blocks.append(["## 11. 上下文警告", *(f"- {item}" for item in context.warnings)])
    if context.assumptions:
        blocks.append(["## 12. 估算假设", *(f"- {item}" for item in context.assumptions)])

    return "\n\n".join("\n".join(str(line) for line in block if line is not None) for block in blocks)


def build_analysis_report(
    query: str,
    answer: str | None = None,
    task_result: object | dict | None = None,
    sources: list[dict] | None = None,
    calculation_metadata: dict | None = None,
    knowledge_metadata: dict | None = None,
    visualization_metadata: dict | None = None,
    simulation_metadata: dict | None = None,
    solution_metadata: dict | None = None,
    comparison_metadata: dict | None = None,
    analysis_mode: dict | None = None,
) -> dict[str, Any]:
    """Build an engineering-oriented Markdown report from answer, sources, and metadata.

    The builder does not call an LLM, create files, fabricate sources, invent
    fluid properties, calculate pressure drop, produce pump curves, or run CFD.
    """

    analysis_mode_map = dict(analysis_mode or {})
    if not _should_generate_report(query, analysis_mode_map):
        return {"generated": False}

    source_items = [item for item in (sources or []) if isinstance(item, dict)]
    calculation = dict(calculation_metadata or {})
    knowledge = dict(knowledge_metadata or {})
    visualization = dict(visualization_metadata or {})
    simulation = dict(simulation_metadata or {})
    solution = dict(solution_metadata or {})
    comparison = dict(comparison_metadata or {})

    context = build_engineering_report_context(
        query=query,
        task=dict(_as_mapping(task_result)),
        sources=source_items,
        calculation_metadata=calculation,
        analysis_metadata={
            "knowledge": knowledge,
            "visualization": visualization,
            "simulation": simulation,
            "solution": solution,
            "comparison": comparison,
        },
    )
    limitations = _collect_limitations(visualization, simulation, solution, comparison)
    next_steps = _collect_next_steps(simulation, solution, comparison)
    plane_wall = calculation.get("tool_name") == "plane_wall_conduction"
    if plane_wall:
        limitations = [
            "当前为一维平壁稳态导热估算，适用假设见下文。",
            "确定性校验只检查已提供的数值与约束，不构成工程认证。",
            "未执行 CFD、网格收敛检查或实验验证，不编造材料或仿真结果。",
        ]
        next_steps = list(context.validation_suggestions)
    content = _render_content(
        context=context,
        query=query,
        sources=source_items,
        calculation_metadata=calculation,
        visualization_metadata=visualization,
        simulation_metadata=simulation,
        solution_metadata=solution,
        comparison_metadata=comparison,
        limitations=limitations,
        next_steps=next_steps,
    )

    return ReportBuildResult(
        generated=True,
        format="markdown",
        title=context.report_subject if plane_wall else "液冷散热分析报告",
        sections=_build_sections(),
        content=content,
        warnings=[
            "报告只整合已有 query、answer、sources 和 metadata，并补充一级工程分析框架。",
            "本阶段不生成 docx/pdf/pptx 文件，不生成图片。",
            "本阶段不运行 CFD，不输出仿真结果。",
        ],
        limitations=limitations,
        source_count=_source_count(source_items),
        includes=_includes(answer, calculation, knowledge, {} if plane_wall else visualization, simulation, {} if plane_wall else solution, comparison),
        exports=[],
        quality=_report_quality(),
        render_hints=_render_hints(),
        physics_validation=_physics_validation(calculation),
    ).to_dict()


__all__ = ["ReportBuildResult", "build_analysis_report"]
