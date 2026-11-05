from __future__ import annotations

import re
from typing import Any, Mapping

from .simulation_task_contracts import SimulationTask, SimulationTaskBuilderResult


_CHECKS = (
    ("model_file", "Model file", True),
    ("geometry", "Geometry definition", True),
    ("materials", "Material definitions", True),
    ("heat_source_power", "Heat-source power", True),
    ("heat_source_location", "Heat-source location", True),
    ("coolant_type", "Coolant type", True),
    ("inlet_temperature", "Coolant inlet temperature", True),
    ("flow_rate", "Coolant flow rate", True),
    ("boundary_conditions", "Outlet or pressure boundary", True),
    ("solver_goal", "Solver goal", True),
    ("mesh_settings", "Mesh and solver settings", False),
    ("property_data", "Validated property data", False),
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first(values: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = values.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _query_inputs(query: str) -> dict[str, Any]:
    text = str(query or "")
    values: dict[str, Any] = {}
    heat = re.search(r"(\d+(?:\.\d+)?)\s*W\b(?!\s*/)", text, re.IGNORECASE)
    if heat:
        values["heat_source_power"] = {"value": float(heat.group(1)), "unit": "W", "source": "user_query"}
    coolant = next((name for name in ("EGW", "PGW", "water", "水", "冷却水") if name.lower() in text.lower()), None)
    if coolant:
        values["coolant_type"] = coolant
    inlet = re.search(r"(?:inlet|入口|进水)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:C|℃|degC)", text, re.IGNORECASE)
    if inlet:
        values["inlet_temperature"] = {"value": float(inlet.group(1)), "unit": "degC", "source": "user_query"}
    flow = re.search(r"(\d+(?:\.\d+)?)\s*(L/min|lpm|kg/s)", text, re.IGNORECASE)
    if flow:
        values["flow_rate"] = {"value": float(flow.group(1)), "unit": flow.group(2), "source": "user_query"}
    return values


def _check(item_id: str, name: str, required: bool, value: Any, detail: str) -> dict[str, Any]:
    status = "ok" if value not in (None, "", [], {}) else ("missing" if required else "warning")
    return {"item_id": item_id, "name": name, "status": status, "detail": detail, "required": required}


def build_simulation_task_builder(
    *,
    query: str,
    model_file: dict[str, Any] | None = None,
    conditions: Mapping[str, Any] | None = None,
    task: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> SimulationTaskBuilderResult:
    """Build a preparation checklist. It never reads geometry or runs a solver."""

    model = _mapping(model_file)
    values = _mapping(conditions)
    query_values = _query_inputs(query)
    meta = _mapping(metadata)
    property_meta = _mapping(meta.get("property_lookup"))

    geometry = _mapping(_first(values, "geometry", "geometry_definition"))
    if not geometry and model.get("object_type") not in (None, "", "unspecified"):
        geometry = {"object_type": model.get("object_type"), "source": "model_file_metadata"}
    materials = _mapping(_first(values, "materials", "material_properties"))
    heat_power = _first(values, "heat_source_power", "heat_load_w", "power_w") or query_values.get("heat_source_power")
    heat_location = _first(values, "heat_source_location", "heat_source_distribution")
    coolant_type = _first(values, "coolant_type", "fluid", "cooling_fluid") or query_values.get("coolant_type")
    inlet_temperature = _first(values, "inlet_temperature", "water_inlet_temperature", "coolant_inlet_temperature") or query_values.get("inlet_temperature")
    flow_rate = _first(values, "flow_rate", "coolant_flow", "liquid_flow_rate") or query_values.get("flow_rate")
    boundaries = _mapping(_first(values, "boundary_conditions", "boundaries"))
    solver_goal = _mapping(_first(values, "solver_goal", "analysis_goal"))
    mesh_settings = _mapping(_first(values, "mesh_settings", "solver_settings"))
    property_data = property_meta.get("source") if property_meta.get("tool_status") == "success" else _first(values, "property_data", "coolant_properties")

    available = {
        "model_file": model if model.get("filename") or model.get("file_id") else None,
        "geometry": geometry,
        "materials": materials,
        "heat_source_power": heat_power,
        "heat_source_location": heat_location,
        "coolant_type": coolant_type,
        "inlet_temperature": inlet_temperature,
        "flow_rate": flow_rate,
        "boundary_conditions": boundaries,
        "solver_goal": solver_goal,
        "mesh_settings": mesh_settings,
        "property_data": property_data,
    }
    checklist = [
        _check(item_id, name, required, available[item_id], "Provided." if available[item_id] not in (None, "", [], {}) else "Input not provided; no value was inferred.")
        for item_id, name, required in _CHECKS
    ]
    missing_inputs = [item["item_id"] for item in checklist if item["status"] == "missing"]
    required_inputs = [item_id for item_id, _, required in _CHECKS if required]
    if "model_file" in missing_inputs:
        readiness_level = "not_ready"
    elif missing_inputs:
        readiness_level = "partially_ready"
    elif not mesh_settings:
        readiness_level = "ready_for_preprocessing"
    else:
        readiness_level = "ready_for_solver_setup"

    heat_sources = []
    if heat_power is not None or heat_location is not None:
        heat_sources.append({"power": heat_power, "location": heat_location})
    task_id = f"simulation-preparation-{model.get('file_id') or 'pending-model'}"
    warnings = [
        "Preparation metadata only; CFD was not executed.",
        "Missing engineering inputs remain unset and were not inferred.",
    ]
    simulation_task = SimulationTask(
        task_id=task_id,
        task_type="simulation_preparation",
        model_file=model,
        geometry=geometry,
        materials=materials,
        heat_sources=heat_sources,
        boundary_conditions=boundaries,
        coolant_loop={"coolant_type": coolant_type, "inlet_temperature": inlet_temperature, "flow_rate": flow_rate},
        solver_goal=solver_goal,
        required_inputs=required_inputs,
        missing_inputs=missing_inputs,
        readiness_level=readiness_level,
        warnings=warnings,
    )
    return SimulationTaskBuilderResult(
        generated=True,
        simulation_ready=readiness_level == "ready_for_solver_setup",
        readiness_level=readiness_level,
        task=simulation_task.to_dict(),
        checklist=checklist,
        missing_inputs=missing_inputs,
        warnings=warnings,
        not_run_reason="cfd_execution_out_of_scope",
        cfd_executed=False,
    )


__all__ = ["build_simulation_task_builder"]
