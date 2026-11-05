from __future__ import annotations

from typing import Any

from ...properties.formatter import format_property_lookup_result
from ...properties.property_lookup_tool import parse_property_lookup_inputs, run_property_lookup_tool
from ...tools.router import detect_property_lookup_tool
from ..metadata_builder import ensure_metadata_contract, property_lookup_metadata, safe_error
from ..state import AgentContext
from .base import BaseAgentStage


class PropertyLookupStage(BaseAgentStage):
    """Execute coolant property lookup as an isolated pipeline stage."""

    name = "property_lookup"

    def run(self, context: AgentContext) -> AgentContext:
        context.metadata = ensure_metadata_contract(context.metadata)
        if not self._should_run(context):
            context.metadata["property_lookup"] = property_lookup_metadata(None)
            context.intermediate["property_lookup_triggered"] = False
            return context

        context.intermediate["property_lookup_triggered"] = True
        try:
            inputs = parse_property_lookup_inputs(context.request.query)
            result = run_property_lookup_tool(inputs)
            context.intermediate["property_lookup_inputs"] = inputs
            context.intermediate["property_lookup_result"] = result
            context.intermediate["property_lookup_error"] = None
            context.metadata["property_lookup"] = property_lookup_metadata(result)
            context.answer = format_property_lookup_result(result)
        except Exception as exc:
            error = safe_error(exc)
            result = self._failed_result(context.request.query, error)
            context.errors.append(f"{self.name}: {error}")
            context.intermediate["property_lookup_inputs"] = {"query": context.request.query}
            context.intermediate["property_lookup_result"] = result
            context.intermediate["property_lookup_error"] = error
            context.metadata["property_lookup"] = property_lookup_metadata(result)
            context.answer = format_property_lookup_result(result)
        return context

    def _should_run(self, context: AgentContext) -> bool:
        task = self._task_to_dict(context.task)
        task_type = str(task.get("task_type") or "")
        if bool(task.get("is_property_lookup")) or task_type == "property_lookup":
            return True
        return detect_property_lookup_tool(context.request.query, task=task) == "coolant_property_lookup"

    @staticmethod
    def _task_to_dict(task: dict[str, Any] | Any | None) -> dict[str, Any]:
        if task is None:
            return {}
        if isinstance(task, dict):
            return dict(task)
        if hasattr(task, "to_dict"):
            value = task.to_dict()
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _failed_result(query: str, error: str) -> dict[str, Any]:
        return {
            "tool_name": "coolant_property_lookup",
            "status": "failed",
            "inputs": {"query": query},
            "fluid": "",
            "normalized_fluid": "",
            "property_name": "",
            "normalized_property_name": "",
            "temperature_c": None,
            "concentration_percent": None,
            "value": None,
            "unit": None,
            "source": None,
            "interpolation": None,
            "warnings": [],
            "missing_fields": [],
            "supported_range": None,
            "error": error,
        }


__all__ = ["PropertyLookupStage"]
