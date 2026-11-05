from __future__ import annotations

from copy import deepcopy
from typing import Any


CARD_IDS = (
    "task_card", "calculation_card", "property_lookup_card", "hydraulics_card",
    "pump_selection_card", "flow_distribution_card", "hydraulic_network_card",
    "thermal_network_card", "thermal_path_card", "sensitivity_card", "report_card",
    "simulation_card", "self_critique_card", "multi_agent_card", "sources_card",
)


def _warnings(block: dict[str, Any]) -> list[str]:
    values = block.get("warnings") or block.get("tool_warnings") or []
    return [str(item)[:240] for item in values[:5]] if isinstance(values, list) else []


def _card(
    card_id: str, title: str, status: str, visible: bool, summary: dict[str, Any],
    data_path: str, priority: int, warnings: list[str], frontend_hint: str,
) -> dict[str, Any]:
    return {
        "card_id": card_id, "title": title, "status": status, "visible": bool(visible),
        "summary": summary, "data_path": data_path, "priority": priority,
        "warnings": warnings, "frontend_hint": frontend_hint,
    }


def build_frontend_metadata_cards(response: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
    task = response.get("task") if isinstance(response.get("task"), dict) else {}
    sources = response.get("sources") if isinstance(response.get("sources"), list) else []

    calc = metadata.get("calculation") if isinstance(metadata.get("calculation"), dict) else {}
    prop = metadata.get("property_lookup") if isinstance(metadata.get("property_lookup"), dict) else {}
    hyd = metadata.get("hydraulics") if isinstance(metadata.get("hydraulics"), dict) else {}
    pump = metadata.get("pump_selection") if isinstance(metadata.get("pump_selection"), dict) else {}
    flow = metadata.get("flow_distribution") if isinstance(metadata.get("flow_distribution"), dict) else {}
    hnet = metadata.get("hydraulic_network") if isinstance(metadata.get("hydraulic_network"), dict) else {}
    tnet = metadata.get("thermal_network") if isinstance(metadata.get("thermal_network"), dict) else {}
    tpath = metadata.get("thermal_path") if isinstance(metadata.get("thermal_path"), dict) else {}
    sens = metadata.get("sensitivity") if isinstance(metadata.get("sensitivity"), dict) else {}
    report = metadata.get("report") if isinstance(metadata.get("report"), dict) else {}
    sim = metadata.get("simulation") if isinstance(metadata.get("simulation"), dict) else {}
    critique = metadata.get("self_critique") if isinstance(metadata.get("self_critique"), dict) else {}
    multi = metadata.get("multi_agent") if isinstance(metadata.get("multi_agent"), dict) else {}

    titles = []
    for source in sources[:3]:
        if isinstance(source, dict):
            title = source.get("title") or source.get("source")
            if isinstance(title, str) and title and not (":\\" in title):
                titles.append(title[:120])

    cards = [
        _card("task_card", "Task", str(task.get("task_type") or response.get("task_type") or "unknown"), True,
              {"task_type": task.get("task_type") or response.get("task_type"), "candidate_tools": list(task.get("candidate_tools") or [])},
              "task", 10, _warnings(task), "status"),
        _card("calculation_card", "Calculation", str(calc.get("tool_status") or "skipped"), bool(calc.get("tool_name")) and calc.get("tool_status") != "skipped",
              {"tool_name": calc.get("tool_name"), "missing_parameters": list(calc.get("missing_parameters") or [])},
              "metadata.calculation", 20, _warnings(calc), "calculation"),
        _card("property_lookup_card", "Property lookup", str(prop.get("tool_status") or "skipped"), bool(prop.get("used_property_lookup")),
              {"tool_name": prop.get("tool_name"), "fluid": prop.get("fluid"), "property_name": prop.get("property_name")},
              "metadata.property_lookup", 20, _warnings(prop), "property"),
        _card("hydraulics_card", "Hydraulics", str(hyd.get("status") or "skipped"), bool(hyd.get("used_hydraulic_calculation")),
              {"tool_name": hyd.get("tool_name"), "missing_parameters": list(hyd.get("missing_parameters") or [])},
              "metadata.hydraulics", 20, _warnings(hyd), "engineering_estimate"),
        _card("pump_selection_card", "Pump selection preparation", str(pump.get("status") or "skipped"), bool(pump.get("generated")),
              {"pump_model_selected": bool(pump.get("pump_model_selected")), "pump_curve_used": bool(pump.get("pump_curve_used")), "missing_inputs": list(pump.get("missing_inputs") or [])},
              "metadata.pump_selection", 30, _warnings(pump), "checklist"),
        _card("flow_distribution_card", "Flow distribution", str(flow.get("status") or "skipped"), bool(flow.get("generated")),
              {
                  "topology": flow.get("topology"),
                  "equal_split_assumption_used": "equal_split_assumption" in list(flow.get("assumptions") or []),
                  "assumptions": list(flow.get("assumptions") or []),
                  "branch_flows_lpm": [
                      row.get("flow_rate_lpm")
                      for row in list((flow.get("result") or {}).get("branches") or [])
                      if isinstance(row, dict)
                  ],
                  "cfd_executed": bool(flow.get("cfd_executed")),
              },
              "metadata.flow_distribution", 30, _warnings(flow), "network"),
        _card("hydraulic_network_card", "Hydraulic network", "enabled" if hnet.get("enabled") else "skipped", bool(hnet.get("enabled")),
              {"topology": hnet.get("topology"), "branch_count": hnet.get("branch_count")},
              "metadata.hydraulic_network", 35, _warnings(hnet), "network"),
        _card("thermal_network_card", "Thermal network", str(tnet.get("status") or "skipped"), bool(tnet.get("generated")),
              {
                  "topology": tnet.get("topology"),
                  "result_scope": "known_thermal_resistance_subpath" if tnet.get("partial_result") else "complete_network",
                  "junction_temperature_c": None if tnet.get("partial_result") else tnet.get("junction_temperature_c"),
                  "known_resistance_subtotal_k_per_w": tnet.get("known_resistance_subtotal_k_per_w"),
                  "known_temperature_rise_c": tnet.get("known_temperature_rise_c"),
                  "missing_inputs": list(tnet.get("missing_inputs") or []),
                  "bottleneck_count": len(tnet.get("bottlenecks") or []),
              },
              "metadata.thermal_network", 30, _warnings(tnet), "thermal_network"),
        _card("thermal_path_card", "Thermal path", "generated" if tpath.get("generated") else "skipped", bool(tpath.get("generated")),
              {
                  "graph_type": tpath.get("graph_type"),
                  "partial_graph": bool(tpath.get("partial_graph")),
                  "final_junction_node_present": bool(tpath.get("final_junction_node_present")),
                  "cfd_executed": bool(tpath.get("cfd_executed")),
              },
              "metadata.thermal_path", 35, _warnings(tpath), "graph"),
        _card("sensitivity_card", "Sensitivity", str(sens.get("status") or "skipped"), bool(sens.get("generated")),
              {"base_metric": sens.get("base_metric"), "target_metric": sens.get("target_metric"), "missing_inputs": list(sens.get("missing_inputs") or [])},
              "metadata.sensitivity", 35, _warnings(sens), "sensitivity"),
        _card("report_card", "Report", "generated" if report.get("generated") else "skipped", bool(report.get("generated")),
              {"template_id": report.get("template_id"), "section_count": len(report.get("sections") or [])},
              "metadata.report", 40, _warnings(report), "report"),
        _card("simulation_card", "Simulation readiness", "enabled" if sim.get("enabled") else "skipped", bool(sim.get("enabled")),
              {"simulation_ready": bool(sim.get("simulation_ready")), "cfd_executed": bool((sim.get("task_builder") or {}).get("cfd_executed")), "missing_input_count": len((sim.get("task_builder") or {}).get("missing_inputs") or [])},
              "metadata.simulation", 40, _warnings(sim), "checklist"),
        _card("self_critique_card", "Self critique", str(critique.get("route") or "skipped"), bool(critique.get("enabled")),
              {"passed": bool(critique.get("passed", True)), "severity": critique.get("severity"), "issue_count": len(critique.get("issues") or [])},
              "metadata.self_critique", 80, _warnings(critique), "quality_gate"),
        _card("multi_agent_card", "Multi-agent shadow", str(multi.get("mode") or "disabled"), bool(multi.get("enabled")),
              {"uses_llm": bool(multi.get("uses_llm")), "worker_count": len(multi.get("worker_trace") or [])},
              "metadata.multi_agent", 90, _warnings(multi), "trace"),
        _card("sources_card", "Sources", "available" if sources else "empty", bool(sources),
              {"count": len(sources), "titles": titles}, "sources", 100, [], "source_summary"),
    ]
    return deepcopy(cards)


__all__ = ["CARD_IDS", "build_frontend_metadata_cards"]
