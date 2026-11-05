from __future__ import annotations

from typing import Any

from ...task_understanding import TaskUnderstandingResult, understand_task
from ..metadata_builder import safe_error
from ..state import AgentContext
from .base import BaseAgentStage


def _task_to_dict(result: TaskUnderstandingResult | dict[str, Any] | Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    if hasattr(result, "to_dict"):
        value = result.to_dict()
        if isinstance(value, dict):
            return dict(value)
    raise TypeError("Task Understanding result must be dict-like")


def _normalize_task_dict(result: TaskUnderstandingResult | dict[str, Any] | Any) -> dict[str, Any]:
    task = _task_to_dict(result)
    task["task_type"] = str(task.get("task_type") or "unknown")
    task["needs_calculation"] = bool(task.get("needs_calculation"))
    task["candidate_tools"] = [str(item) for item in task.get("candidate_tools") or []]
    task["is_property_lookup"] = bool(task.get("is_property_lookup"))

    needs_visualization = bool(task.get("needs_visualization"))
    needs_report = bool(task.get("needs_report"))
    needs_comparison = bool(task.get("needs_comparison"))
    needs_simulation = bool(task.get("needs_simulation"))
    task["needs_visualization"] = needs_visualization
    task["needs_report"] = needs_report
    task["needs_comparison"] = needs_comparison
    task["needs_simulation"] = needs_simulation
    task["requires_visualization"] = needs_visualization
    task["requires_report"] = needs_report
    task["requires_comparison"] = needs_comparison
    task["requires_simulation_readiness"] = needs_simulation
    return task


class TaskStage(BaseAgentStage):
    """Run the existing deterministic Task Understanding rules."""

    name = "task"

    def run(self, context: AgentContext) -> AgentContext:
        query = context.request.query
        try:
            result = understand_task(query)
            task = _normalize_task_dict(result)
        except Exception as exc:
            error = safe_error(exc)
            context.errors.append(f"{self.name}: {error}")
            result = TaskUnderstandingResult(
                task_type="unknown",
                needs_retrieval=False,
                original_query=query,
                normalized_query=query,
                warnings=[f"task_understanding_failed: {error}"],
            )
            task = _normalize_task_dict(result)

        warnings = [str(item) for item in task.get("warnings") or [] if item]
        for warning in warnings:
            if warning not in context.warnings:
                context.warnings.append(warning)

        context.task = task
        context.intermediate["task_result"] = result
        context.intermediate["task_result_dict"] = dict(task)
        context.intermediate["task_type"] = task["task_type"]
        context.intermediate["task_warnings"] = warnings
        return context


__all__ = ["TaskStage"]
