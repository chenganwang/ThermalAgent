from __future__ import annotations

from typing import Any

from ..properties.formatter import format_property_lookup_result
from .contracts import ToolExecutionResult


def format_tool_execution_result(result: ToolExecutionResult) -> str:
    """Render a ToolExecutionResult without inventing missing values."""

    if result.tool_name == "coolant_property_lookup":
        payload = dict(result.result or {})
        if "status" not in payload:
            payload["status"] = result.status
        if "warnings" not in payload:
            payload["warnings"] = list(result.warnings)
        if "error" not in payload:
            payload["error"] = result.error
        return format_property_lookup_result(payload)

    if result.status == "success":
        lines = [f"Tool {result.tool_name} completed successfully."]
        if result.formula:
            lines.append(f"Formula: {result.formula}")
        if result.result:
            lines.append("Result:")
            for key, value in result.result.items():
                if value is not None:
                    lines.append(f"- {key}: {value}")
        if result.steps:
            lines.append("Steps:")
            lines.extend(f"- {step}" for step in result.steps)
        if result.assumptions:
            lines.append("Assumptions:")
            lines.extend(f"- {item}" for item in result.assumptions)
        if result.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {item}" for item in result.warnings)
        return "\n".join(lines)

    if result.status == "missing_params":
        missing = ", ".join(result.missing_parameters) or "unknown"
        return f"Tool {result.tool_name} cannot run because required parameters are missing: {missing}."

    if result.status == "unknown_tool":
        tool_name = result.tool_name or "unknown"
        return f"Unknown tool: {tool_name}."

    if result.status == "failed":
        message = result.error or "tool execution failed"
        return f"Tool {result.tool_name} failed: {message}."

    if result.status == "skipped":
        return "No calculation tool was selected."

    message = result.error or "unrecognized tool execution status"
    return f"Tool {result.tool_name} returned status {result.status}: {message}."


def _result_conclusion(result: dict[str, Any]) -> str:
    tool = result.get("tool_name")
    values = result.get("result") or {}
    if tool == "thermal_resistance_network_solve" and result.get("thermal_network_status") == "partial_result":
        subtotal = values.get("known_resistance_subtotal_k_per_w")
        delta_t = values.get("known_temperature_rise_c")
        return (
            "结论：以下结果仅覆盖已知热阻子链；由于缺少冷板热阻，无法计算完整结温。"
            f"已知子链热阻小计为 {subtotal} K/W，已知段温升为 {delta_t} K。"
        )
    if result.get("status") != "ok":
        missing = ", ".join(result.get("missing_parameters") or [])
        if missing:
            return f"结论：目前不能给出具体唯一数值，因为缺少必要参数：{missing}。"
        return f"结论：无法完成计算：{result.get('error') or '输入参数不足或非法'}。"
    if tool == "required_thermal_resistance":
        return f"结论：所需最大总热阻约为 {values.get('R_required_K_per_W')} K/W，允许温差为 {values.get('allowed_delta_T_K')} K。"
    if tool == "junction_temperature_estimate":
        return f"结论：估算芯片温度约为 {values.get('T_j_C')} degC，温升约为 {values.get('temperature_rise_K')} K。"
    if tool == "conduction_resistance":
        return f"结论：该导热层一维导热热阻约为 {values.get('R_cond_K_per_W')} K/W。"
    if tool == "plane_wall_conduction":
        return f"结论：该平壁一维稳态导热量约为 {values.get('heat_rate_W')} W。"
    if tool == "coolant_temperature_rise":
        return f"结论：冷却液温升约为 {values.get('delta_T_K')} K。"
    if tool == "liquid_flow_rate_required":
        if values.get("volume_flow_L_min") is None:
            return f"结论：所需质量流量约为 {values.get('mass_flow_kg_s')} kg/s；由于未提供密度，未计算体积流量。"
        return f"结论：所需质量流量约为 {values.get('mass_flow_kg_s')} kg/s，体积流量约为 {values.get('volume_flow_L_min')} L/min。"
    if tool == "liquid_pressure_drop_estimate":
        return (
            f"结论：一维工程估算压降约为 {values.get('pressure_drop_kpa')} kPa，"
            f"对应液柱扬程约为 {values.get('required_head_m')} m。该结果不是 CFD 或实验结果。"
        )
    if tool == "liquid_network_flow_distribution":
        if "equal_split_assumption" in list(values.get("assumptions") or result.get("assumptions") or []):
            return (
                "结论：基于用户明确声明的完全相同并联支路，按理想化一维等阻力假设进行等流量分配。"
                "该结果未考虑歧管分配不均、制造偏差或局部阻力差异，不是 CFD 或实验验证结果。"
            )
        return (
            "Conclusion: the series/parallel liquid-network result is a one-dimensional equivalent-network "
            "estimate or preparation output. It is not CFD or experimental evidence, and no branch resistance "
            "or geometry was inferred."
        )
    if tool == "thermal_resistance_network_solve":
        return (
            "Conclusion: the result is a one-dimensional steady thermal-resistance network estimate. "
            "It is not CFD, experimental evidence, or package-level simulation, and no missing resistance "
            "or thermal boundary was inferred."
        )
    if tool == "pump_selection_preparer":
        return (
            "结论：已整理泵选型需求与缺项清单，但未选择具体泵型号，"
            "也未使用或伪造泵曲线、效率或 NPSH 数据。"
        )
    return "结论：已完成计算。"


def _source_lines(sources: list[dict[str, Any]] | None) -> list[str]:
    lines: list[str] = []
    for source in list(sources or [])[:3]:
        title = source.get("title") or source.get("book_title") or f"doc_id={source.get('doc_id')}"
        page = source.get("page_start")
        chunk = source.get("chunk_id") or source.get("chunk_index")
        lines.append(f"- [{source.get('rank')}] {title}, page={page}, chunk={chunk}")
    return lines


def format_tool_answer(result: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> str:
    """Render a calculation result as the agent's answer string."""

    lines = [_result_conclusion(result), "", f"公式：{result.get('formula') or '未提供'}"]

    missing = [str(item) for item in result.get("missing_parameters") or []]
    if missing:
        lines.extend(["", "需要补充的参数："])
        lines.extend(f"- {item}" for item in missing)

    steps = [str(item) for item in result.get("calculation_steps") or []]
    if steps:
        lines.extend(["", "代入计算："])
        lines.extend(f"- {step}" for step in steps)

    values = result.get("result") or {}
    if values:
        lines.extend(["", "结果："])
        partial_thermal = (
            result.get("tool_name") == "thermal_resistance_network_solve"
            and result.get("thermal_network_status") == "partial_result"
        )
        safe_partial_keys = {
            "status", "topology", "partial_result", "incomplete_network",
            "known_resistance_subtotal_k_per_w", "known_temperature_rise_c",
            "known_elements", "missing_elements", "completeness_ratio",
            "missing_parameters", "warnings", "cfd_executed",
        }
        for key, value in values.items():
            if partial_thermal and key not in safe_partial_keys:
                continue
            if value is not None:
                lines.append(f"- {key}: {value}")

    unit_check = result.get("unit_check") or {}
    messages = [str(item) for item in unit_check.get("messages") or []]
    if messages:
        lines.extend(["", f"单位校验：{unit_check.get('status', 'unknown')}"])
        lines.extend(f"- {message}" for message in messages)

    assumptions = [str(item) for item in result.get("assumptions") or []]
    if assumptions:
        lines.extend(["", "显式假设："])
        lines.extend(f"- {item}" for item in assumptions)

    warnings: list[str] = []
    for item in result.get("warnings") or []:
        text = str(item)
        if text and text not in warnings:
            warnings.append(text)
    note = str(result.get("engineering_note") or "").strip()
    if note and note not in warnings:
        warnings.append(note)
    if warnings:
        lines.extend(["", "工程边界与警告："])
        lines.extend(f"- {item}" for item in warnings)

    src = _source_lines(sources)
    lines.extend(["", "RAG 与计算关系："])
    if src:
        lines.append("- 检索资料用于解释液冷散热原理和工程背景；数值结果由本地确定性计算工具完成。")
        lines.extend(["", "可参考的知识库来源："])
        lines.extend(src)
    else:
        lines.append("- 当前计算基于通用传热/能量守恒公式，未从当前知识库检索到强匹配来源。")
    return "\n".join(lines)
