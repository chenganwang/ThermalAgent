from __future__ import annotations

from typing import Any

from .contracts import SupervisorPlan
from .role_cards import list_role_cards


_CALCULATION_TOOLS = {
    "required_thermal_resistance",
    "junction_temperature_estimate",
    "conduction_resistance",
    "coolant_temperature_rise",
    "liquid_flow_rate_required",
    "liquid_pressure_drop_estimate",
    "liquid_network_flow_distribution",
    "thermal_resistance_network_solve",
}

_BASELINE_WORKERS = [
    "task_understanding_agent",
    "query_rewrite_agent",
    "retrieval_agent",
]


def _truthy(mapping: dict[str, Any], *keys: str) -> bool:
    return any(bool(mapping.get(key)) for key in keys)


def build_supervisor_plan(
    query: str,
    task: dict[str, Any],
    rewrite: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SupervisorPlan:
    """Describe the expected workers without changing routing or execution."""

    task_view = dict(task or {})
    metadata_view = dict(metadata or {})
    query_type = str(task_view.get("task_type") or "unknown")
    selected = list(_BASELINE_WORKERS)
    rationale = ["baseline_pipeline_observers"]

    candidate_tools = set(task_view.get("candidate_tools") or [])
    calculation = metadata_view.get("calculation") or {}
    if (
        bool(task_view.get("needs_calculation"))
        or bool(candidate_tools & _CALCULATION_TOOLS)
        or bool(calculation.get("used_calculation"))
    ):
        selected.append("calculation_agent")
        rationale.append("calculation_requested_or_observed")

    property_lookup = metadata_view.get("property_lookup") or {}
    if (
        bool(task_view.get("is_property_lookup"))
        or query_type == "property_lookup"
        or bool(property_lookup.get("used_property_lookup"))
    ):
        selected.append("property_lookup_agent")
        rationale.append("property_lookup_requested_or_observed")

    flow_distribution = metadata_view.get("flow_distribution") or {}
    hydraulic_network = metadata_view.get("hydraulic_network") or {}
    if (
        bool(task_view.get("flow_distribution_requested"))
        or "liquid_network_flow_distribution" in candidate_tools
        or bool(flow_distribution.get("generated"))
        or bool(hydraulic_network.get("enabled"))
    ):
        selected.append("hydraulic_network_agent")
        rationale.append("hydraulic_network_requested_or_observed")

    thermal_network = metadata_view.get("thermal_network") or {}
    if (
        bool(task_view.get("thermal_network_requested"))
        or "thermal_resistance_network_solve" in candidate_tools
        or bool(thermal_network.get("generated"))
    ):
        selected.append("thermal_network_agent")
        rationale.append("thermal_network_requested_or_observed")

    analysis_requested = _truthy(
        task_view,
        "requires_report",
        "requires_comparison",
        "requires_visualization",
        "requires_simulation_readiness",
        "analysis_report_mode",
    ) or query_type in {"report", "comparison", "visualization", "simulation_readiness"}
    analysis_workflow = metadata_view.get("analysis_workflow") or {}
    report = metadata_view.get("report") or {}
    comparison = metadata_view.get("comparison") or {}
    visualization = metadata_view.get("visualization") or {}
    simulation = metadata_view.get("simulation") or {}
    if analysis_requested or any(
        (
            bool(analysis_workflow.get("enabled")),
            bool(report.get("generated")),
            bool(comparison.get("generated")),
            bool(visualization.get("generated")),
            bool(simulation.get("enabled")),
        )
    ):
        selected.append("analysis_agent")
        rationale.append("analysis_output_requested_or_observed")

    if bool(task_view.get("requires_report")) or query_type == "report" or bool(report.get("generated")):
        selected.append("report_agent")
        rationale.append("report_requested_or_observed")

    task_builder = simulation.get("task_builder") or {}
    if (
        bool(task_view.get("requires_simulation_readiness"))
        or query_type == "simulation_readiness"
        or bool(task_builder.get("generated"))
    ):
        selected.append("simulation_task_agent")
        rationale.append("simulation_readiness_requested_or_observed")

    simulation_mode = metadata_view.get("simulation_mode") or {}
    simulation_plan = metadata_view.get("simulation_plan") or {}
    if bool(simulation_mode.get("enabled")) or bool(simulation_plan):
        selected.extend(
            [
                "simulation_planner_agent",
                "matlab_execution_agent",
                "simulation_safety_agent",
            ]
        )
        rationale.append("conversational_simulation_mode_observed")

    selected.extend(["critique_agent", "answer_agent"])
    selected = list(dict.fromkeys(selected))
    observable_roles = [card.role_id for card in list_role_cards() if card.role_id != "supervisor_agent"]
    skipped = [role_id for role_id in observable_roles if role_id not in selected]

    return SupervisorPlan(
        plan_id=f"shadow-plan-{query_type}",
        mode="shadow",
        query_type=query_type,
        selected_workers=selected,
        skipped_workers=skipped,
        rationale=rationale,
        created_by="rule_based_supervisor",
        uses_llm=False,
    )


__all__ = ["build_supervisor_plan"]
