from __future__ import annotations

from typing import Any

from .analysis_intent import detect_analysis_intent
from .calculation_intent import detect_calculation_intent
from .entity_extractor import extract_entities
from .intent_classifier import build_intent, classify_task_type
from .hydraulics_intent import detect_hydraulics_intent
from .hydraulic_network_intent import detect_hydraulic_network_intent
from .thermal_network_intent import detect_thermal_network_intent
from .normalizer import normalize_query
from .property_lookup import detect_property_lookup, is_irrelevant_or_analogy_query
from .task_types import TASK_TYPES, TaskUnderstandingResult
from .visualization_intent import detect_visualization_intent


def understand_task(query: str, options: dict[str, Any] | None = None) -> TaskUnderstandingResult:
    """Understand a user query with deterministic local rules."""

    original = query or ""
    normalized = normalize_query(original)
    options = options or {}
    entities = extract_entities(normalized)
    task_type, confidence = classify_task_type(normalized)
    calculation = detect_calculation_intent(normalized)
    property_lookup = detect_property_lookup(normalized)
    visualization = detect_visualization_intent(normalized)
    analysis = detect_analysis_intent(normalized, options)
    hydraulics = detect_hydraulics_intent(normalized)
    hydraulic_network = detect_hydraulic_network_intent(normalized)
    thermal_network = detect_thermal_network_intent(normalized)
    analogy_request = is_irrelevant_or_analogy_query(normalized)

    is_property_lookup = bool(property_lookup.get("is_property_lookup") or task_type == "property_lookup")
    is_irrelevant_or_analogy = bool(analogy_request or task_type == "irrelevant_or_analogy")
    calculation_request = bool(calculation.get("needs_calculation"))
    candidate_tools = list(calculation.get("candidate_tools") or [])
    pump_selection_requested = bool(hydraulics.get("pump_selection_requested"))
    flow_distribution_requested = bool(hydraulic_network.get("flow_distribution_requested"))
    thermal_network_requested = bool(thermal_network.get("thermal_network_requested"))
    bottleneck_requested = bool(thermal_network.get("bottleneck_requested"))
    sensitivity_requested = bool(thermal_network.get("sensitivity_requested"))
    thermal_model_plan_requested = bool(thermal_network.get("model_plan_requested"))
    if hydraulic_network.get("needs_calculation"):
        calculation_request = True
        for candidate in hydraulic_network.get("candidate_tools") or []:
            if candidate not in candidate_tools:
                candidate_tools.insert(0, candidate)
    if hydraulics.get("needs_calculation"):
        calculation_request = True
        for candidate in hydraulics.get("candidate_tools") or []:
            if candidate not in candidate_tools:
                candidate_tools.insert(0, candidate)
    if hydraulic_network.get("needs_calculation"):
        for candidate in reversed(list(hydraulic_network.get("candidate_tools") or [])):
            if candidate in candidate_tools:
                candidate_tools.remove(candidate)
            candidate_tools.insert(0, candidate)
    if thermal_network.get("needs_calculation"):
        calculation_request = True
        for candidate in reversed(list(thermal_network.get("candidate_tools") or [])):
            if candidate in candidate_tools:
                candidate_tools.remove(candidate)
            candidate_tools.insert(0, candidate)
    if is_property_lookup and calculation_request and candidate_tools:
        is_property_lookup = False
        if task_type == "property_lookup":
            task_type = "general_qa"
    if is_property_lookup or is_irrelevant_or_analogy:
        calculation_request = False
        candidate_tools = []
        pump_selection_requested = False
        flow_distribution_requested = False
        thermal_network_requested = False
        bottleneck_requested = False
        sensitivity_requested = False

    if thermal_model_plan_requested:
        task_type = "simulation"
    elif is_property_lookup:
        task_type = "property_lookup"
    elif is_irrelevant_or_analogy:
        task_type = "irrelevant_or_analogy"
    elif thermal_network.get("is_thermal_network") or hydraulic_network.get("is_hydraulic_network") or hydraulics.get("is_hydraulics"):
        task_type = "calculation"
    elif calculation_request and candidate_tools and task_type == "general_qa":
        task_type = "calculation"

    needs_visualization = bool(visualization.get("needs_visualization"))
    needs_report = bool(analysis.get("needs_report"))
    needs_comparison = bool(analysis.get("needs_comparison") or task_type == "comparison")
    needs_simulation = bool(analysis.get("needs_simulation") or thermal_model_plan_requested)
    warnings: list[str] = []

    if calculation_request:
        warnings.append("检测到工程计算意图；将优先尝试调用本地热管理计算工具，结果仅用于一级工程估算。")

    if is_property_lookup:
        warnings.append("检测到冷却液物性查表意图；若来源未同时覆盖流体类型、浓度、温度、物性名、数值和单位，则不能给出确定物性值。")

    if is_irrelevant_or_analogy:
        warnings.append("检测到跨域类比或弱相关问题；回答应区分教学类比和工程设计依据。")

    if needs_visualization:
        warnings.append("检测到图结构或可视化表达意图；本阶段仅标记结构化需求，不生成 CFD 云图。")

    if needs_report:
        warnings.append("检测到分析报告需求；报告应保持规则式工程分析边界，不作为真实仿真报告。")

    if needs_simulation:
        warnings.append("检测到仿真准备需求；当前只做准备状态识别，不执行 CFD 求解。")

    if not normalized:
        warnings.append("输入为空，无法进行有效任务理解。")

    if entities:
        confidence = min(0.98, confidence + 0.05)
    if any([calculation_request, needs_visualization, needs_report, needs_comparison, needs_simulation]):
        confidence = min(0.98, confidence + 0.05)

    raw_signals = {
        "calculation": calculation.get("signals", []),
        "property_lookup": property_lookup.get("signals", []),
        "visualization": visualization.get("signals", []),
        "analysis": analysis.get("signals", []),
        "hydraulics": hydraulics.get("signals", []),
        "hydraulic_network": hydraulic_network.get("signals", []),
        "thermal_network": thermal_network.get("signals", []),
    }

    return TaskUnderstandingResult(
        task_type=task_type if task_type in TASK_TYPES else "general_qa",
        domain="thermal_management",
        entities=entities,
        intent=build_intent(normalized, task_type, entities),
        needs_retrieval=bool(normalized),
        needs_calculation=calculation_request,
        needs_visualization=needs_visualization,
        confidence=round(confidence, 2),
        original_query=original,
        normalized_query=normalized,
        warnings=warnings,
        candidate_tools=candidate_tools,
        properties=list(property_lookup.get("properties") or []),
        needs_report=needs_report,
        needs_comparison=needs_comparison,
        needs_simulation=needs_simulation,
        is_property_lookup=is_property_lookup,
        is_irrelevant_or_analogy=is_irrelevant_or_analogy,
        pump_selection_requested=pump_selection_requested,
        flow_distribution_requested=flow_distribution_requested,
        thermal_network_requested=thermal_network_requested,
        bottleneck_requested=bottleneck_requested,
        sensitivity_requested=sensitivity_requested,
        raw_signals=raw_signals,
    )
