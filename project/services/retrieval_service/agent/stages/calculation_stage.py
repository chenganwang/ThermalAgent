from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from ...tools.executor import parse_tool_inputs
from ...tools.pump_selection_preparer import prepare_pump_selection
from ...tools.flow_distribution_preparer import prepare_flow_distribution
from ...tools.thermal_sensitivity_preparer import prepare_thermal_sensitivity
from ...tools.router import detect_calculation_tool
from ...tools.specs import TOOL_FUNCTIONS
from ..metadata_builder import (
    calculation_metadata,
    ensure_metadata_contract,
    flow_distribution_metadata,
    hydraulic_network_metadata,
    hydraulics_metadata,
    pump_selection_metadata,
    sensitivity_metadata,
    safe_error,
    thermal_network_metadata,
    thermal_path_metadata,
)
from ..state import AgentContext
from ..engineering_run import execute_calculation_plan, plan_calculation
from .base import BaseAgentStage


_ALLOWED_CALCULATION_TOOLS = {
    "required_thermal_resistance",
    "junction_temperature_estimate",
    "conduction_resistance",
    "plane_wall_conduction",
    "coolant_temperature_rise",
    "liquid_flow_rate_required",
    "liquid_pressure_drop_estimate",
    "liquid_network_flow_distribution",
    "thermal_resistance_network_solve",
}


def _task_to_dict(task: dict[str, Any] | Any | None) -> dict[str, Any]:
    if task is None:
        return {}
    if isinstance(task, dict):
        return task
    if hasattr(task, "to_dict"):
        value = task.to_dict()
        if isinstance(value, dict):
            return value
    return {}


def _is_property_lookup_task(task: dict[str, Any]) -> bool:
    task_type = str(task.get("task_type") or "")
    return task_type == "property_lookup" or bool(task.get("is_property_lookup"))


def _is_pump_selection_task(task: dict[str, Any]) -> bool:
    return bool(task.get("pump_selection_requested")) or str(task.get("task_type") or "") == "pump_selection"


def _execute_legacy_calculation(query: str, tool_name: str, observer=None) -> dict[str, Any]:
    parse = parse_tool_inputs(query, tool_name)
    plan = plan_calculation(tool_name, parse)
    if observer is not None:
        observer(plan)
    return execute_calculation_plan(plan, parse, TOOL_FUNCTIONS[str(tool_name)], observer=observer)


def _execute_pump_selection(query: str) -> dict[str, Any]:
    parsed = parse_tool_inputs(query, "liquid_pressure_drop_estimate")
    requirements = dict(parsed.get("pump_requirements") or {})
    prepared = prepare_pump_selection(requirements)
    payload = prepared.to_dict()
    return {
        "tool_name": "pump_selection_preparer",
        "status": "ok",
        "inputs": requirements,
        "formula": "Pump duty preparation from required flow, head, and/or pressure drop; no model selection.",
        "calculation_steps": [
            "Collect required flow and pressure/head duty.",
            "Build vendor-selection checklist.",
            "Leave pump curve, operating point, and NPSH unverified.",
        ],
        "result": payload,
        "pump_selection": payload,
        "unit_check": {"status": "passed", "messages": ["Flow, pressure, and head remain explicit engineering units."]},
        "warnings": list(prepared.warnings),
        "assumptions": [],
        "engineering_note": "Preparation only; no pump model or vendor curve was selected.",
        "error": None if prepared.status != "missing_params" else "Missing pump selection requirements.",
        "missing_parameters": list(prepared.missing_inputs),
    }


def _thermal_sensitivity_perturbation(query: str) -> dict[str, Any] | None:
    conductivity = re.search(
        r"TIM\s*(?:导热率|导热系数)?\s*从\s*(\d+(?:\.\d+)?)\s*(?:提高|增加|变)?到\s*(\d+(?:\.\d+)?)\s*W/mK",
        query,
        re.IGNORECASE,
    )
    if conductivity:
        return {
            "parameter": "thermal_conductivity_w_mk",
            "element_id": "tim",
            "from": float(conductivity.group(1)),
            "to": float(conductivity.group(2)),
        }
    resistance = re.search(
        r"(?:热阻|resistance)\s*(?:项)?\s*([A-Za-z0-9_-]+)?\s*(?:降低|下降|reduce(?:d)?\s+by)\s*(\d+(?:\.\d+)?)\s*%",
        query,
        re.IGNORECASE,
    )
    if resistance:
        return {
            "parameter": "resistance_k_per_w",
            "element_id": resistance.group(1) or "",
            "reduction_percent": float(resistance.group(2)),
        }
    return None


class CalculationStage(BaseAgentStage):
    """Run deterministic thermal calculation tools in the staged pipeline."""

    name = "calculation"

    def __init__(self, observer=None):
        self.observer = observer

    def _detect_tool(self, context: AgentContext) -> str | None:
        query = context.request.query
        task = _task_to_dict(context.task)
        if _is_property_lookup_task(task):
            return None
        tool_name = detect_calculation_tool(query, task=task)
        if tool_name not in _ALLOWED_CALCULATION_TOOLS:
            return None
        return tool_name

    def run(self, context: AgentContext) -> AgentContext:
        context.metadata = ensure_metadata_contract(context.metadata)
        try:
            task = _task_to_dict(context.task)
            if _is_pump_selection_task(task):
                result = _execute_pump_selection(context.request.query)
                context.metadata["pump_selection"] = pump_selection_metadata(result.get("pump_selection"))
                context.intermediate["calculation_result"] = result
                context.intermediate["calculation_error"] = result.get("error")
                context.intermediate["calculation_triggered"] = False
                context.intermediate["pump_selection_result"] = result.get("pump_selection")
                return context

            tool_name = self._detect_tool(context)
            if tool_name is None:
                context.metadata["calculation"] = calculation_metadata(None)
                context.intermediate["calculation_result"] = None
                context.intermediate["calculation_error"] = None
                context.intermediate["calculation_triggered"] = False
                return context

            result = _execute_legacy_calculation(context.request.query, tool_name, self.observer)
            if tool_name == "liquid_network_flow_distribution":
                network = dict(result.get("inputs", {}).get("network") or {})
                prepared = prepare_flow_distribution(network)
                context.metadata["flow_distribution"] = flow_distribution_metadata(result, prepared)
                context.metadata["hydraulic_network"] = hydraulic_network_metadata(network, result)
                context.intermediate["calculation_result"] = result
                context.intermediate["calculation_error"] = result.get("error") if result.get("status") == "error" else None
                context.intermediate["calculation_triggered"] = False
                context.intermediate["flow_distribution_result"] = deepcopy(result)
                context.intermediate["flow_distribution_preparation"] = deepcopy(prepared)
                return context
            if tool_name == "thermal_resistance_network_solve":
                network = dict(result.get("inputs", {}).get("network") or {})
                task = _task_to_dict(context.task)
                sensitivity_plan = None
                if bool(task.get("sensitivity_requested")):
                    sensitivity_plan = prepare_thermal_sensitivity(
                        network,
                        _thermal_sensitivity_perturbation(context.request.query),
                    )
                    result["sensitivity"] = sensitivity_plan.to_dict()
                context.metadata["thermal_network"] = thermal_network_metadata(result)
                context.metadata["thermal_path"] = thermal_path_metadata(result)
                context.metadata["sensitivity"] = sensitivity_metadata(sensitivity_plan)
                context.intermediate["calculation_result"] = result
                context.intermediate["calculation_error"] = result.get("error") if result.get("status") == "error" else None
                context.intermediate["calculation_triggered"] = False
                context.intermediate["thermal_network_result"] = deepcopy(result)
                if sensitivity_plan is not None:
                    context.intermediate["thermal_sensitivity_result"] = sensitivity_plan.to_dict()
                return context
            if tool_name == "liquid_pressure_drop_estimate":
                context.metadata["hydraulics"] = hydraulics_metadata(result)
                context.intermediate["calculation_result"] = result
                context.intermediate["calculation_error"] = result.get("error") if result.get("status") == "error" else None
                context.intermediate["calculation_triggered"] = False
                context.intermediate["hydraulic_result"] = result
                return context
            context.metadata["calculation"] = calculation_metadata(result)
            context.intermediate["calculation_result"] = result
            context.intermediate["calculation_error"] = result.get("error") if result.get("status") == "error" else None
            context.intermediate["calculation_triggered"] = True
            return context
        except Exception as exc:
            calculation_error = safe_error(exc)
            result = {
                "tool_name": "unknown",
                "status": "error",
                "inputs": {},
                "formula": "",
                "calculation_steps": [],
                "result": {},
                "unit_check": {"status": "failed", "messages": [calculation_error]},
                "warnings": [],
                "assumptions": [],
                "engineering_note": "",
                "error": calculation_error,
                "missing_parameters": [],
            }
            context.metadata["calculation"] = calculation_metadata(result)
            context.intermediate["calculation_result"] = result
            context.intermediate["calculation_error"] = calculation_error
            context.intermediate["calculation_triggered"] = False
            context.errors.append(f"{self.name}: {calculation_error}")
            return context


__all__ = ["CalculationStage"]
