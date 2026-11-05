from __future__ import annotations

from typing import Any

from ..state import AgentContext
from .contracts import AgentRoleCard, SupervisorPlan, WorkerExecutionRecord


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _role_completed(role_id: str, context: AgentContext) -> bool:
    metadata = _mapping(context.metadata)
    if role_id == "task_understanding_agent":
        return bool(context.task)
    if role_id == "query_rewrite_agent":
        return bool(context.rewrite)
    if role_id == "retrieval_agent":
        return bool(context.sources)
    if role_id == "calculation_agent":
        calculation = _mapping(metadata.get("calculation"))
        return bool(calculation.get("used_calculation")) or calculation.get("tool_status") in {"ok", "success"}
    if role_id == "property_lookup_agent":
        lookup = _mapping(metadata.get("property_lookup"))
        return bool(lookup.get("used_property_lookup")) or lookup.get("tool_status") in {"ok", "success"}
    if role_id == "hydraulic_network_agent":
        flow = _mapping(metadata.get("flow_distribution"))
        network = _mapping(metadata.get("hydraulic_network"))
        return bool(flow.get("generated")) or bool(network.get("enabled"))
    if role_id == "thermal_network_agent":
        return bool(_mapping(metadata.get("thermal_network")).get("generated"))
    if role_id == "analysis_agent":
        workflow = _mapping(metadata.get("analysis_workflow"))
        return bool(workflow.get("enabled")) or any(
            bool(_mapping(metadata.get(key)).get("generated"))
            for key in ("report", "comparison", "visualization")
        ) or bool(_mapping(metadata.get("simulation")).get("enabled"))
    if role_id == "report_agent":
        return bool(_mapping(metadata.get("report")).get("generated"))
    if role_id == "simulation_task_agent":
        simulation = _mapping(metadata.get("simulation"))
        return bool(_mapping(simulation.get("task_builder")).get("generated"))
    if role_id == "simulation_planner_agent":
        return bool(_mapping(metadata.get("simulation_plan")).get("plan_id"))
    if role_id == "matlab_execution_agent":
        execution = _mapping(metadata.get("simulation_execution"))
        return execution.get("status") in {"completed", "completed_with_warnings", "success"} and execution.get("executed") is not False
    if role_id == "simulation_safety_agent":
        return bool(_mapping(metadata.get("simulation_mode")).get("enabled"))
    if role_id == "critique_agent":
        return bool(_mapping(metadata.get("self_critique")).get("enabled"))
    if role_id == "answer_agent":
        return bool(context.answer)
    return False


_ROLE_METADATA_KEYS = {
    "calculation_agent": "calculation",
    "property_lookup_agent": "property_lookup",
    "hydraulic_network_agent": "flow_distribution",
    "thermal_network_agent": "thermal_network",
    "analysis_agent": "analysis_workflow",
    "report_agent": "report",
    "simulation_planner_agent": "simulation_plan",
    "matlab_execution_agent": "simulation_execution",
    "simulation_safety_agent": "simulation_mode",
    "critique_agent": "self_critique",
}
_FAILED_STATUSES = {"error", "failed", "invalid_data", "unknown_tool", "timeout"}
_BLOCKED_STATUSES = {
    "blocked", "missing_params", "missing_parameters", "missing_data", "partial_result",
    "unsupported", "unsupported_fluid", "unsupported_property", "unsupported_range",
    "not_implemented", "requires_infrastructure",
}
_SKIPPED_STATUSES = {"skipped", "disabled", "cancelled", "canceled", "not_requested"}


def _observed_outcome(card: AgentRoleCard, context: AgentContext) -> tuple[str, int]:
    """Read existing evidence only; these are observations, not worker events."""
    metadata = _mapping(context.metadata)
    details = _mapping(metadata.get(_ROLE_METADATA_KEYS.get(card.role_id, "")))
    if card.role_id == "simulation_task_agent":
        details = _mapping(_mapping(metadata.get("simulation")).get("task_builder"))
    if card.role_id == "retrieval_agent":
        details = _mapping(context.intermediate.get("retrieval_result"))
    tool_result = _mapping(details.get("tool_result"))
    raw_status = str(details.get("tool_status") or details.get("status") or tool_result.get("status") or "").lower()

    # The same exception may be present in stage context and packaged metadata.
    # Count its distinct evidence once, and never copy private exception text.
    errors: set[str] = set()
    candidates = [details.get("error")]
    if isinstance(details.get("errors"), list):
        candidates.extend(details["errors"])
    if card.stage_name:
        candidates.append(metadata.get(f"{card.stage_name}_error"))
        candidates.extend(
            error.split(":", 1)[1].strip() for error in context.errors
            if isinstance(error, str) and error.startswith(f"{card.stage_name}:")
        )
    for error in candidates:
        if error:
            errors.add(str(error).strip())
    if raw_status in _BLOCKED_STATUSES:
        return "blocked", len(errors)
    if errors or raw_status in _FAILED_STATUSES:
        return "failed", max(1, len(errors))
    if raw_status in _SKIPPED_STATUSES:
        return "skipped", 0

    if card.role_id == "retrieval_agent":
        if context.task.get("needs_retrieval") is False or not context.request.query.strip():
            return "skipped", 0
        if details:
            return ("completed" if details.get("query") else "skipped"), 0
        if context.sources or "retrieval_latency_ms" in metadata:
            return "completed", 0
        return "pending", 0
    if card.role_id in {"analysis_agent", "critique_agent", "simulation_safety_agent"} and details.get("enabled") is False:
        return "skipped", 0
    return ("completed" if _role_completed(card.role_id, context) else "pending"), 0


def _output_summary(role_id: str, context: AgentContext) -> dict[str, Any]:
    metadata = _mapping(context.metadata)
    summaries: dict[str, dict[str, Any]] = {
        "task_understanding_agent": {
            "task_present": bool(context.task),
            "task_type": str(context.task.get("task_type") or "unknown"),
        },
        "query_rewrite_agent": {"rewrite_present": bool(context.rewrite)},
        "retrieval_agent": {"source_count": len(context.sources)},
        "calculation_agent": {
            "used_calculation": bool(_mapping(metadata.get("calculation")).get("used_calculation")),
            "tool_status": _mapping(metadata.get("calculation")).get("tool_status"),
            "result_present": bool(_mapping(metadata.get("calculation")).get("tool_result")),
        },
        "property_lookup_agent": {
            "used_property_lookup": bool(_mapping(metadata.get("property_lookup")).get("used_property_lookup")),
            "tool_status": _mapping(metadata.get("property_lookup")).get("tool_status"),
            "result_present": bool(_mapping(metadata.get("property_lookup")).get("tool_result")),
        },
        "hydraulic_network_agent": {
            "generated": bool(_mapping(metadata.get("flow_distribution")).get("generated")),
            "status": _mapping(metadata.get("flow_distribution")).get("status"),
            "topology": _mapping(metadata.get("hydraulic_network")).get("topology"),
            "branch_count": _mapping(metadata.get("hydraulic_network")).get("branch_count"),
        },
        "thermal_network_agent": {
            "generated": bool(_mapping(metadata.get("thermal_network")).get("generated")),
            "status": _mapping(metadata.get("thermal_network")).get("status"),
            "topology": _mapping(metadata.get("thermal_network")).get("topology"),
            "bottleneck_count": len(_mapping(metadata.get("thermal_network")).get("bottlenecks") or []),
            "thermal_path_generated": bool(_mapping(metadata.get("thermal_path")).get("generated")),
        },
        "analysis_agent": {
            "workflow_enabled": bool(_mapping(metadata.get("analysis_workflow")).get("enabled")),
        },
        "report_agent": {"generated": bool(_mapping(metadata.get("report")).get("generated"))},
        "simulation_task_agent": {
            "generated": bool(
                _mapping(_mapping(metadata.get("simulation")).get("task_builder")).get("generated")
            )
        },
        "simulation_planner_agent": {
            "plan_id": _mapping(metadata.get("simulation_plan")).get("plan_id"),
            "execution_allowed": _mapping(metadata.get("simulation_plan")).get("execution_allowed"),
            "missing_input_count": len(_mapping(metadata.get("simulation_plan")).get("missing_inputs") or []),
        },
        "matlab_execution_agent": {
            "status": _mapping(metadata.get("simulation_execution")).get("status"),
            "executed": bool(_mapping(metadata.get("simulation_execution")).get("executed")),
            "solver_backend": _mapping(metadata.get("simulation_execution")).get("solver_backend"),
        },
        "simulation_safety_agent": {
            "confirmed": bool(_mapping(metadata.get("simulation_mode")).get("confirmed")),
            "pending_confirmation": bool(_mapping(metadata.get("simulation_mode")).get("pending_confirmation")),
            "cfd_executed": bool(_mapping(metadata.get("simulation_execution")).get("cfd_executed")),
        },
        "critique_agent": {
            "enabled": bool(_mapping(metadata.get("self_critique")).get("enabled")),
            "passed": _mapping(metadata.get("self_critique")).get("passed"),
        },
        "answer_agent": {"answer_present": bool(context.answer)},
    }
    return summaries.get(role_id, {})


def build_worker_trace(
    context: AgentContext,
    plan: SupervisorPlan,
    role_cards: list[AgentRoleCard],
) -> list[WorkerExecutionRecord]:
    """Build lightweight worker status records from already-produced context."""

    selected = set(plan.selected_workers)
    records: list[WorkerExecutionRecord] = []
    for card in role_cards:
        if card.role_id == "supervisor_agent":
            continue
        status, error_count = _observed_outcome(card, context) if card.role_id in selected else ("skipped", 0)
        skipped = status == "skipped"
        completed = status == "completed"
        started = status in {"completed", "failed"}
        if card.role_id == "matlab_execution_agent" and _mapping(context.metadata.get("simulation_execution")).get("executed") is False:
            started = False
        records.append(
            WorkerExecutionRecord(
                worker_id=card.role_id,
                role_id=card.role_id,
                stage_name=card.stage_name or "analysis",
                status=status,
                started=started,
                completed=completed,
                skipped=skipped,
                error_count=error_count,
                warnings=[],
                input_summary={
                    "query_present": bool(context.request.query),
                    "task_type": str(context.task.get("task_type") or "unknown"),
                    "source_count": len(context.sources),
                },
                output_summary=_output_summary(card.role_id, context),
            )
        )
    return records


__all__ = ["build_worker_trace"]
