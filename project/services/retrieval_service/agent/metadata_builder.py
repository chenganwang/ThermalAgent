from __future__ import annotations

from copy import deepcopy
from typing import Any

from .multi_agent.metadata import default_multi_agent_metadata


def safe_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:400]


def calculation_metadata(result: dict[str, Any] | None) -> dict[str, Any]:
    if result and result.get("tool_name") in {
        "liquid_pressure_drop_estimate",
        "liquid_network_flow_distribution",
        "thermal_resistance_network_solve",
        "pump_selection_preparer",
    }:
        result = None
    if not result:
        return {
            "used_calculation": False,
            "tool_name": None,
            "tool_status": "skipped",
            "tool_inputs": {},
            "tool_result": {},
            "tool_formula": None,
            "tool_steps": [],
            "tool_warnings": [],
            "missing_parameters": [],
            "assumptions": [],
        }
    missing_parameters = list(result.get("missing_parameters") or [])
    status = str(result.get("status") or "error")
    contract_status = "missing_params" if missing_parameters and status in {"error", "failed"} else status
    return {
        "used_calculation": status == "ok",
        "tool_name": result.get("tool_name"),
        "tool_status": contract_status,
        "tool_inputs": result.get("inputs") or {},
        "tool_result": result.get("result") or {},
        "tool_formula": result.get("formula"),
        "tool_steps": result.get("calculation_steps") or [],
        "tool_warnings": result.get("warnings") or [],
        "missing_parameters": missing_parameters,
        "assumptions": result.get("assumptions") or [],
        "unit_check": result.get("unit_check") or {},
        "error": result.get("error"),
        "raw": result,
    }


def property_lookup_metadata(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {
            "used_property_lookup": False,
            "tool_name": None,
            "tool_status": "skipped",
            "tool_inputs": {},
            "tool_result": {},
            "property_name": None,
            "fluid": None,
            "temperature_c": None,
            "concentration_percent": None,
            "value": None,
            "unit": None,
            "source": None,
            "interpolation": None,
            "warnings": [],
        }
    return {
        "used_property_lookup": True,
        "tool_name": result.get("tool_name") or "coolant_property_lookup",
        "tool_status": result.get("status") or "failed",
        "tool_inputs": result.get("inputs") or {},
        "tool_result": result,
        "property_name": result.get("normalized_property_name") or result.get("property_name"),
        "fluid": result.get("normalized_fluid") or result.get("fluid"),
        "temperature_c": result.get("temperature_c"),
        "concentration_percent": result.get("concentration_percent"),
        "value": result.get("value"),
        "unit": result.get("unit"),
        "source": result.get("source"),
        "interpolation": result.get("interpolation"),
        "warnings": result.get("warnings") or [],
        "missing_fields": result.get("missing_fields") or [],
        "supported_range": result.get("supported_range"),
        "error": result.get("error"),
    }


def hydraulics_metadata(result: dict[str, Any] | None = None) -> dict[str, Any]:
    default = {
        "used_hydraulic_calculation": False,
        "tool_name": None,
        "status": "skipped",
        "tool_inputs": {},
        "tool_result": {},
        "warnings": [],
        "missing_parameters": [],
    }
    if not result or result.get("tool_name") != "liquid_pressure_drop_estimate":
        return default
    hydraulic_status = str(
        result.get("hydraulic_status")
        or ("missing_params" if result.get("missing_parameters") else None)
        or ("success" if result.get("status") == "ok" else "failed")
    )
    return {
        "used_hydraulic_calculation": True,
        "tool_name": "liquid_pressure_drop_estimate",
        "status": hydraulic_status,
        "tool_inputs": deepcopy(result.get("inputs") or {}),
        "tool_result": deepcopy(result),
        "warnings": list(result.get("warnings") or []),
        "missing_parameters": list(result.get("missing_parameters") or []),
    }


def pump_selection_metadata(result: Any | None = None) -> dict[str, Any]:
    default = {
        "generated": False,
        "status": "skipped",
        "required_flow_rate_lpm": None,
        "required_head_m": None,
        "required_pressure_drop_kpa": None,
        "selection_checklist": [],
        "missing_inputs": [],
        "warnings": [],
        "pump_model_selected": False,
        "pump_curve_used": False,
    }
    if result is None:
        return default
    if hasattr(result, "to_dict"):
        data = result.to_dict()
    elif isinstance(result, dict):
        data = dict(result)
    else:
        return default
    return merge_metadata(default, data)


def flow_distribution_metadata(
    result: dict[str, Any] | None = None,
    preparation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default = {
        "generated": False,
        "status": "skipped",
        "tool_name": None,
        "topology": None,
        "result": {},
        "checklist": [],
        "missing_inputs": [],
        "warnings": [],
        "cfd_executed": False,
    }
    if not result and not preparation:
        return default
    raw = deepcopy(result or {})
    prepared = deepcopy(preparation or {})
    payload = deepcopy(raw.get("result") or prepared.get("result") or {})
    status = str(
        raw.get("network_status")
        or payload.get("status")
        or prepared.get("status")
        or "missing_params"
    )
    if status == "estimated":
        status = "success"
    return merge_metadata(
        default,
        {
            "generated": True,
            "status": status,
            "tool_name": "liquid_network_flow_distribution",
            "topology": payload.get("topology") or prepared.get("topology"),
            "result": payload,
            "assumptions": list(payload.get("assumptions") or raw.get("assumptions") or []),
            "checklist": list(prepared.get("checklist") or []),
            "missing_inputs": list(
                prepared.get("missing_inputs")
                or raw.get("missing_parameters")
                or payload.get("missing_parameters")
                or []
            ),
            "warnings": list(
                prepared.get("warnings")
                or raw.get("warnings")
                or payload.get("warnings")
                or []
            ),
            "cfd_executed": False,
        },
    )


def hydraulic_network_metadata(
    network: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default = {
        "enabled": False,
        "topology": None,
        "branch_count": None,
        "component_count": None,
        "network_model": None,
        "assumptions": [],
        "warnings": [],
    }
    if not network and not result:
        return default
    model = deepcopy(network or (result or {}).get("inputs", {}).get("network") or {})
    payload = deepcopy((result or {}).get("result") or {})
    return merge_metadata(
        default,
        {
            "enabled": True,
            "topology": model.get("topology") or payload.get("topology") or "unknown",
            "branch_count": len(model.get("branches") or []) if isinstance(model.get("branches"), list) else None,
            "component_count": len(model.get("components") or []) if isinstance(model.get("components"), list) else None,
            "network_model": model or None,
            "identical_branches": bool(
                "identical_branches_explicit" in list(model.get("assumptions") or [])
            ),
            "equal_split_assumption_used": bool(
                "equal_split_assumption" in list(payload.get("assumptions") or [])
            ),
            "assumptions": list(model.get("assumptions") or payload.get("assumptions") or []),
            "warnings": list(model.get("warnings") or payload.get("warnings") or []),
        },
    )


def thermal_network_metadata(result: dict[str, Any] | None = None) -> dict[str, Any]:
    default = {
        "generated": False,
        "status": "skipped",
        "tool_name": None,
        "topology": None,
        "total_resistance_k_per_w": None,
        "junction_temperature_c": None,
        "allowable_total_resistance_k_per_w": None,
        "margin_c": None,
        "elements": [],
        "node_temperatures": [],
        "bottlenecks": [],
        "missing_inputs": [],
        "warnings": [],
        "cfd_executed": False,
    }
    if not result:
        return default
    raw = deepcopy(result)
    payload = deepcopy(raw.get("result") or {})
    return merge_metadata(
        default,
        {
            "generated": True,
            "status": raw.get("thermal_network_status") or payload.get("status") or "missing_params",
            "tool_name": "thermal_resistance_network_solve",
            "topology": payload.get("topology"),
            "total_resistance_k_per_w": payload.get("total_resistance_k_per_w"),
            "junction_temperature_c": payload.get("junction_temperature_c"),
            "allowable_total_resistance_k_per_w": payload.get("allowable_total_resistance_k_per_w"),
            "margin_c": payload.get("margin_c"),
            "partial_result": bool(payload.get("partial_result")),
            "incomplete_network": bool(payload.get("incomplete_network")),
            "known_resistance_subtotal_k_per_w": payload.get("known_resistance_subtotal_k_per_w"),
            "known_temperature_rise_c": payload.get("known_temperature_rise_c"),
            "known_elements": list(payload.get("known_elements") or []),
            "missing_elements": list(payload.get("missing_elements") or []),
            "completeness_ratio": payload.get("completeness_ratio"),
            "elements": list(payload.get("elements") or []),
            "node_temperatures": list(payload.get("node_temperatures") or []),
            "bottlenecks": list(payload.get("bottlenecks") or []),
            "missing_inputs": list(raw.get("missing_parameters") or payload.get("missing_parameters") or []),
            "warnings": list(raw.get("warnings") or payload.get("warnings") or []),
            "cfd_executed": False,
        },
    )


def thermal_path_metadata(result: dict[str, Any] | None = None) -> dict[str, Any]:
    default = {
        "generated": False,
        "graph_type": None,
        "graph": None,
        "warnings": [],
        "cfd_executed": False,
    }
    payload = deepcopy((result or {}).get("result") or {})
    graph = deepcopy(payload.get("thermal_path_graph"))
    if not isinstance(graph, dict) or not graph.get("generated"):
        return default
    return merge_metadata(
        default,
        {
            "generated": True,
            "graph_type": "thermal_resistance_network",
            "graph": graph,
            "partial_graph": bool(graph.get("partial_graph")),
            "incomplete_network": bool(graph.get("incomplete_network")),
            "final_junction_node_present": bool(graph.get("final_junction_node_present")),
            "warnings": list(graph.get("warnings") or []),
            "cfd_executed": False,
        },
    )


def sensitivity_metadata(result: Any | None = None) -> dict[str, Any]:
    default = {
        "generated": False,
        "status": "skipped",
        "base_metric": None,
        "target_metric": None,
        "result": {},
        "perturbations": [],
        "missing_inputs": [],
        "warnings": [],
        "cfd_executed": False,
    }
    if result is None:
        return default
    data = result.to_dict() if hasattr(result, "to_dict") else deepcopy(result if isinstance(result, dict) else {})
    if not data:
        return default
    return merge_metadata(
        default,
        {
            "generated": bool(data.get("generated")),
            "status": data.get("status") or "missing_params",
            "base_metric": data.get("base_metric"),
            "target_metric": data.get("target_metric"),
            "result": data,
            "perturbations": list(data.get("perturbations") or []),
            "missing_inputs": list(data.get("missing_inputs") or []),
            "warnings": list(data.get("warnings") or []),
            "cfd_executed": False,
        },
    )


def build_default_metadata() -> dict[str, Any]:
    """Build metadata defaults required by the /agent/answer contract."""

    return {
        "calculation": calculation_metadata(None),
        "knowledge": {
            "synthesized": False,
            "answer_style": None,
            "source_language": "mixed/en",
            "template_type": None,
        },
        "analysis_mode": {
            "enabled": False,
            "mode": "default_chat",
            "reason": "default",
            "requested_outputs": [],
        },
        "analysis_workflow": {
            "enabled": False,
            "mode": "default_chat",
            "requested_outputs": [],
            "warnings": [],
            "errors": [],
        },
        "visualization": {"generated": False},
        "simulation": {"enabled": False},
        "simulation_mode": {
            "enabled": False,
            "state": "off",
            "plan_id": None,
            "requires_confirmation": False,
            "pending_confirmation": False,
            "confirmed": False,
            "executed": False,
            "cancelled": False,
            "warnings": [],
            "errors": [],
            "persistence": "in_memory_process_local",
            "ui_actions": ["show_plan", "show_confirm", "show_cancel", "show_status"],
            "button_state": {
                "show_plan": False,
                "show_confirm": False,
                "show_cancel": False,
                "show_status": False,
            },
        },
        "simulation_plan": {
            "generated": False,
            "plan_id": None,
            "objective": None,
            "user_question": None,
            "simulation_type": None,
            "model_id": None,
            "selected_model_id": None,
            "selected_model_name": None,
            "selection_reason": None,
            "candidate_models": [],
            "model_selection_confidence": 0.0,
            "inputs": {},
            "missing_inputs": [],
            "checklist": [],
            "execution_steps": [],
            "expected_outputs": [],
            "matlab_entrypoint": None,
            "can_execute_now": False,
            "not_executable_reason": None,
            "requires_confirmation": True,
        },
        "matlab": {
            "configured": False,
            "available": False,
            "connected": False,
            "engine_import_ok": False,
            "engine_started": False,
            "matlab_version": None,
            "python_version": None,
            "matlab_root": None,
            "engine_error": None,
            "last_check_at": None,
            "execution_mode": "unavailable",
            "uses_real_matlab": False,
        },
        "simulation_execution": {
            "plan_id": None,
            "executed": False,
            "status": "not_started",
            "solver_backend": None,
            "backend": None,
            "matlab_entrypoint": None,
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "result": {},
            "result_files": [],
            "warnings": [],
            "errors": [],
            "cfd_executed": False,
            "evidence": {},
        },
        "solution": {"generated": False},
        "comparison": {"generated": False},
        "report": {"generated": False},
        "retrieval": {
            "enabled": False,
            "source_count": 0,
            "has_sources": False,
            "retrieval_query_present": False,
            "score_summary": {"min": None, "max": None, "count": 0},
            "warnings": [],
        },
        "self_critique": {
            "enabled": False,
            "passed": True,
            "severity": "ok",
            "issues": [],
            "repair_action": "none",
            "route": "skipped",
            "requires_human_review": False,
            "warnings": [],
            "repaired": False,
            "safe_repair_applied": False,
        },
        "property_lookup": property_lookup_metadata(None),
        "hydraulics": hydraulics_metadata(None),
        "pump_selection": pump_selection_metadata(None),
        "flow_distribution": flow_distribution_metadata(None),
        "hydraulic_network": hydraulic_network_metadata(None),
        "thermal_network": thermal_network_metadata(None),
        "thermal_path": thermal_path_metadata(None),
        "sensitivity": sensitivity_metadata(None),
        "multi_agent": default_multi_agent_metadata(),
    }


def merge_metadata(base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively merge metadata dictionaries without mutating inputs."""

    merged = deepcopy(base or {})
    for key, value in dict(extra or {}).items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_metadata(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def ensure_metadata_contract(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return metadata with required keys present and existing values preserved."""

    ensured = merge_metadata(build_default_metadata(), metadata or {})
    calculation = ensured.get("calculation")
    if isinstance(calculation, dict):
        ensured["calculation"] = merge_metadata(calculation_metadata(None), calculation)
    property_lookup = ensured.get("property_lookup")
    if isinstance(property_lookup, dict):
        ensured["property_lookup"] = merge_metadata(property_lookup_metadata(None), property_lookup)
    hydraulics = ensured.get("hydraulics")
    if isinstance(hydraulics, dict):
        ensured["hydraulics"] = merge_metadata(hydraulics_metadata(None), hydraulics)
    pump_selection = ensured.get("pump_selection")
    if isinstance(pump_selection, dict):
        ensured["pump_selection"] = merge_metadata(pump_selection_metadata(None), pump_selection)
    flow_distribution = ensured.get("flow_distribution")
    if isinstance(flow_distribution, dict):
        ensured["flow_distribution"] = merge_metadata(flow_distribution_metadata(None), flow_distribution)
    hydraulic_network = ensured.get("hydraulic_network")
    if isinstance(hydraulic_network, dict):
        ensured["hydraulic_network"] = merge_metadata(hydraulic_network_metadata(None), hydraulic_network)
    thermal_network = ensured.get("thermal_network")
    if isinstance(thermal_network, dict):
        ensured["thermal_network"] = merge_metadata(thermal_network_metadata(None), thermal_network)
    thermal_path = ensured.get("thermal_path")
    if isinstance(thermal_path, dict):
        ensured["thermal_path"] = merge_metadata(thermal_path_metadata(None), thermal_path)
    sensitivity = ensured.get("sensitivity")
    if isinstance(sensitivity, dict):
        ensured["sensitivity"] = merge_metadata(sensitivity_metadata(None), sensitivity)
    task_model_assist = ensured.get("task_model_assist")
    if isinstance(task_model_assist, dict):
        task_model_assist["used_for_routing"] = False
    return ensured


def package_self_critique_metadata(result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Complete the self-critique contract without changing workflow fields."""

    default = build_default_metadata()["self_critique"]
    packaged = merge_metadata(default, result or {})
    packaged["enabled"] = bool(packaged.get("enabled"))
    packaged["passed"] = bool(packaged.get("passed"))
    packaged["issues"] = list(packaged.get("issues") or [])
    packaged["severity"] = str(packaged.get("severity") or "ok")
    packaged["route"] = str(packaged.get("route") or "skipped")
    packaged["repair_action"] = str(packaged.get("repair_action") or "none")
    packaged["warnings"] = list(packaged.get("warnings") or [])
    packaged["repaired"] = bool(packaged.get("repaired"))
    packaged["safe_repair_applied"] = bool(packaged.get("safe_repair_applied") or packaged["repaired"])
    return packaged


def package_analysis_metadata(
    metadata: dict[str, Any] | None,
    analysis_mode: dict[str, Any] | None,
    analysis_workflow: dict[str, Any] | None,
) -> dict[str, Any]:
    """Package existing analysis outputs without dropping unrelated metadata."""

    packaged = ensure_metadata_contract(metadata)
    workflow = dict(analysis_workflow or {})
    packaged["analysis_mode"] = merge_metadata(
        packaged.get("analysis_mode") or {},
        analysis_mode or {},
    )
    packaged["analysis_workflow"] = merge_metadata(
        packaged.get("analysis_workflow") or {},
        {
            "enabled": bool(workflow.get("enabled")),
            "mode": workflow.get("mode") or "default_chat",
            "requested_outputs": list(workflow.get("requested_outputs") or []),
            "warnings": list(workflow.get("warnings") or []),
            "errors": list(workflow.get("errors") or []),
        },
    )
    defaults = {
        "visualization": {"generated": False},
        "simulation": {"enabled": False},
        "solution": {"generated": False},
        "comparison": {"generated": False},
        "report": {"generated": False},
    }
    for key, default in defaults.items():
        output = workflow.get(key)
        if bool(workflow.get("enabled")):
            packaged[key] = merge_metadata(
                packaged.get(key) or default,
                output if isinstance(output, dict) else default,
            )
        elif key not in packaged:
            packaged[key] = deepcopy(default)
    return packaged


def build_knowledge_metadata(
    *,
    calculation_result: dict[str, Any] | None,
    sources: list[dict[str, Any]],
    knowledge_template: str,
) -> dict[str, Any]:
    synthesized = calculation_result is None and (
        bool(sources) or knowledge_template in {"property_lookup", "irrelevant_or_analogy"}
    )
    return {
        "synthesized": synthesized,
        "answer_style": "structured_zh" if synthesized else None,
        "source_language": "mixed/en",
        "template_type": knowledge_template if calculation_result is None else None,
    }


def build_agent_metadata(
    *,
    hits_count: int,
    retrieval_latency_ms: int,
    retrieval_error: str | None,
    retrieval_plan: dict[str, Any] | None,
    used_memory: bool,
    calculation: dict[str, Any],
    calculation_result: dict[str, Any] | None,
    calculation_error: str | None,
    knowledge: dict[str, Any],
    analysis_mode_meta: dict[str, Any],
    analysis_workflow: dict[str, Any],
    llm_enabled: bool,
    property_lookup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    calculation_status = calculation["tool_status"]
    pump_result = None
    if calculation_result and calculation_result.get("tool_name") == "pump_selection_preparer":
        pump_result = calculation_result.get("pump_selection") or calculation_result.get("result")
    network_result = calculation_result if calculation_result and calculation_result.get("tool_name") == "liquid_network_flow_distribution" else None
    thermal_result = calculation_result if calculation_result and calculation_result.get("tool_name") == "thermal_resistance_network_solve" else None
    network_model = deepcopy((network_result or {}).get("inputs", {}).get("network") or {})
    metadata = {
        "retrieval_count": hits_count,
        "retrieval_latency_ms": retrieval_latency_ms,
        "retrieval_error": retrieval_error,
        "retrieval_plan": retrieval_plan,
        "used_memory": used_memory,
        "used_calculation": bool(calculation["used_calculation"]),
        "tool_name": calculation["tool_name"],
        "tool_status": calculation_status,
        "tool_inputs": calculation["tool_inputs"],
        "tool_result": calculation["tool_result"],
        "tool_formula": calculation["tool_formula"],
        "tool_steps": calculation["tool_steps"],
        "tool_warnings": calculation["tool_warnings"],
        "missing_parameters": calculation["missing_parameters"],
        "assumptions": calculation["assumptions"],
        "calculation": calculation,
        "calculation_status": calculation_status if calculation_result else None,
        "calculation_tool": calculation["tool_name"],
        "calculation_error": calculation_error,
        "calculation_result": calculation_result,
        "property_lookup": property_lookup or property_lookup_metadata(None),
        "hydraulics": hydraulics_metadata(calculation_result),
        "pump_selection": pump_selection_metadata(pump_result),
        "flow_distribution": flow_distribution_metadata(network_result),
        "hydraulic_network": hydraulic_network_metadata(network_model, network_result),
        "thermal_network": thermal_network_metadata(thermal_result),
        "thermal_path": thermal_path_metadata(thermal_result),
        "sensitivity": sensitivity_metadata((thermal_result or {}).get("sensitivity")),
        "knowledge": knowledge,
        "analysis_mode": analysis_mode_meta,
        "analysis_workflow": {
            "enabled": bool(analysis_workflow.get("enabled")),
            "mode": analysis_workflow.get("mode"),
            "requested_outputs": analysis_workflow.get("requested_outputs") or [],
            "warnings": analysis_workflow.get("warnings") or [],
            "errors": analysis_workflow.get("errors") or [],
        },
        "visualization": analysis_workflow.get("visualization") or {"generated": False},
        "simulation": analysis_workflow.get("simulation") or {"enabled": False},
        "solution": analysis_workflow.get("solution") or {"generated": False},
        "comparison": analysis_workflow.get("comparison") or {"generated": False},
        "report": analysis_workflow.get("report") or {"generated": False},
        "llm_enabled": llm_enabled,
    }
    return ensure_metadata_contract(metadata)


__all__ = [
    "build_agent_metadata",
    "build_default_metadata",
    "build_knowledge_metadata",
    "calculation_metadata",
    "ensure_metadata_contract",
    "flow_distribution_metadata",
    "hydraulic_network_metadata",
    "hydraulics_metadata",
    "merge_metadata",
    "package_analysis_metadata",
    "package_self_critique_metadata",
    "property_lookup_metadata",
    "pump_selection_metadata",
    "safe_error",
    "sensitivity_metadata",
    "thermal_network_metadata",
    "thermal_path_metadata",
]
