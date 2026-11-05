from __future__ import annotations

from copy import deepcopy
from typing import Any

from .thermal_network_contracts import ThermalNetworkSolveResult
from .thermal_bottleneck_analyzer import analyze_thermal_bottlenecks
from .thermal_path_builder import build_thermal_path_graph


THERMAL_NETWORK_FORMULA = (
    "series: R_total=sum(R_i); parallel: R_eq=1/sum(1/R_i); "
    "T_j=T_ref+Q*R_total; R_allowed=(T_j_allowed-T_ref)/Q"
)


def _result(status: str, topology: str, **kwargs: Any) -> ThermalNetworkSolveResult:
    return ThermalNetworkSolveResult(
        status=status,
        topology=topology if topology in {"series", "parallel", "mixed", "unknown"} else "unknown",
        formula=THERMAL_NETWORK_FORMULA,
        **kwargs,
    )


def _resolve_element(element: dict[str, Any], index: int) -> tuple[dict[str, Any], list[str], str | None]:
    row = deepcopy(element or {})
    element_id = str(row.get("element_id") or f"element_{index + 1}")
    row["element_id"] = element_id
    direct = row.get("resistance_k_per_w")
    if direct is not None:
        if float(direct) <= 0:
            return row, [], f"{element_id}.resistance_k_per_w must be positive"
        row["resistance_k_per_w"] = float(direct)
        row.setdefault("resistance_source", "explicit")
        return row, [], None

    element_type = str(row.get("element_type") or "explicit").lower()
    if element_type in {"conduction", "tim", "solid"}:
        required = ("thickness_m", "thermal_conductivity_w_mk", "area_m2")
        missing = [f"{element_id}.{name}" for name in required if row.get(name) is None]
        if missing:
            return row, missing, None
        thickness = float(row["thickness_m"])
        conductivity = float(row["thermal_conductivity_w_mk"])
        area = float(row["area_m2"])
        if min(thickness, conductivity, area) <= 0:
            return row, [], f"{element_id} conduction inputs must be positive"
        row["resistance_k_per_w"] = thickness / (conductivity * area)
        row["resistance_source"] = "calculated_conduction"
        return row, [], None

    if element_type in {"convection", "convective"}:
        required = ("heat_transfer_coefficient_w_m2k", "area_m2")
        missing = [f"{element_id}.{name}" for name in required if row.get(name) is None]
        if missing:
            return row, missing, None
        coefficient = float(row["heat_transfer_coefficient_w_m2k"])
        area = float(row["area_m2"])
        if min(coefficient, area) <= 0:
            return row, [], f"{element_id} convection inputs must be positive"
        row["resistance_k_per_w"] = 1.0 / (coefficient * area)
        row["resistance_source"] = "calculated_convection"
        return row, [], None

    missing_name = row.get("missing_parameter_name")
    return row, [str(missing_name or f"{element_id}.resistance_k_per_w_or_complete_physical_inputs")], None


def _equivalent(topology: str, resistances: list[float]) -> tuple[float | None, str | None]:
    if not resistances:
        return None, None
    if any(value <= 0 for value in resistances):
        return None, "thermal resistance values must be positive"
    if topology == "series":
        return sum(resistances), None
    if topology == "parallel":
        return 1.0 / sum(1.0 / value for value in resistances), None
    return None, "mixed topology requires an explicit nested structure"


def _resolve_network(data: dict[str, Any], path: str = "network") -> tuple[float | None, list[dict[str, Any]], list[str], str | None]:
    topology = str(data.get("topology") or "unknown").lower()
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for index, element in enumerate(list(data.get("elements") or [])):
        row, row_missing, error = _resolve_element(element, index)
        resolved.append(row)
        missing.extend(row_missing)
        if error:
            return None, resolved, missing, error

    resistances = [float(row["resistance_k_per_w"]) for row in resolved if row.get("resistance_k_per_w") is not None]
    components = list(data.get("components") or [])
    if topology == "mixed":
        combination = str(data.get("combination") or "").lower()
        if combination not in {"series", "parallel"} or not components:
            missing.append(f"{path}.explicit_nested_structure")
            return None, resolved, missing, None
        component_resistances: list[float] = []
        for index, component in enumerate(components):
            value, child_rows, child_missing, error = _resolve_network(dict(component or {}), f"{path}.components[{index}]")
            resolved.extend(child_rows)
            missing.extend(child_missing)
            if error:
                return None, resolved, missing, error
            if value is not None:
                component_resistances.append(value)
        if missing:
            return None, resolved, missing, None
        value, error = _equivalent(combination, component_resistances)
        return value, resolved, [], error

    if components:
        for index, component in enumerate(components):
            value, child_rows, child_missing, error = _resolve_network(dict(component or {}), f"{path}.components[{index}]")
            resolved.extend(child_rows)
            missing.extend(child_missing)
            if error:
                return None, resolved, missing, error
            if value is not None:
                resistances.append(value)
    if missing:
        return None, resolved, missing, None
    value, error = _equivalent(topology, resistances)
    return value, resolved, [], error


def _node_temperatures(elements: list[dict[str, Any]], heat_load_w: float, reference_temperature_c: float) -> list[dict[str, Any]]:
    nodes = [{"node_id": "reference", "name": "Reference boundary", "temperature_c": reference_temperature_c, "node_type": "reference"}]
    cumulative = 0.0
    for index, element in enumerate(elements):
        cumulative += float(element["resistance_k_per_w"])
        nodes.append(
            {
                "node_id": f"after_{element['element_id']}",
                "name": f"After {element.get('name') or element['element_id']}",
                "temperature_c": reference_temperature_c + heat_load_w * cumulative,
                "node_type": "junction" if index == len(elements) - 1 else "interface",
            }
        )
    return nodes


def _partial_node_temperatures(
    elements: list[dict[str, Any]], heat_load_w: float, reference_temperature_c: float
) -> list[dict[str, Any]]:
    nodes = [{
        "node_id": "reference",
        "name": "Reference boundary",
        "temperature_c": reference_temperature_c,
        "node_type": "reference",
        "is_final_junction_temperature": False,
    }]
    cumulative = 0.0
    for index, element in enumerate(elements):
        cumulative += float(element["resistance_k_per_w"])
        nodes.append({
            "node_id": f"after_{element['element_id']}",
            "name": f"After {element.get('name') or element['element_id']}",
            "temperature_c": reference_temperature_c + heat_load_w * cumulative,
            "node_type": "known_subpath_end" if index == len(elements) - 1 else "interface",
            "is_final_junction_temperature": False,
        })
    return nodes


def solve_thermal_resistance_network(network: dict[str, Any] | None) -> ThermalNetworkSolveResult:
    data = deepcopy(network or {})
    topology = str(data.get("topology") or "unknown").lower()
    heat_load = data.get("heat_load_w")
    reference = data.get("reference_temperature_c")
    allowable = data.get("allowable_junction_temperature_c")
    assumptions = list(data.get("assumptions") or [])
    warnings = list(data.get("warnings") or [])

    if topology not in {"series", "parallel", "mixed"}:
        return _result("missing_params", "unknown", missing_parameters=["topology"], assumptions=assumptions, warnings=warnings)
    if heat_load is not None and float(heat_load) <= 0:
        return _result("failed", topology, error="heat_load_w must be positive", assumptions=assumptions, warnings=warnings)

    total, elements, missing, error = _resolve_network(data)
    allowed_total = None
    if allowable is not None or reference is not None or heat_load is not None:
        missing_allowed = [name for name, value in (("heat_load_w", heat_load), ("reference_temperature_c", reference), ("allowable_junction_temperature_c", allowable)) if value is None]
        if not missing_allowed:
            if float(allowable) <= float(reference):
                return _result("failed", topology, elements=elements, error="allowable_junction_temperature_c must exceed reference_temperature_c")
            allowed_total = (float(allowable) - float(reference)) / float(heat_load)

    if error:
        return _result("failed", topology, heat_load_w=heat_load, reference_temperature_c=reference, elements=elements, missing_parameters=missing, assumptions=assumptions, warnings=warnings, error=error)
    if total is None and not (allowed_total is not None and not data.get("elements") and not data.get("components")):
        if not missing:
            missing = ["elements_or_explicit_nested_structure"]
        known_elements = [row for row in elements if row.get("resistance_k_per_w") is not None]
        missing_elements = [
            str(row.get("element_id"))
            for row in elements
            if row.get("resistance_k_per_w") is None and row.get("element_id")
        ]
        if topology == "series" and known_elements and missing_elements:
            known_subtotal = sum(float(row["resistance_k_per_w"]) for row in known_elements)
            known_delta = float(heat_load) * known_subtotal if heat_load is not None else None
            partial_nodes = (
                _partial_node_temperatures(known_elements, float(heat_load), float(reference))
                if heat_load is not None and reference is not None
                else []
            )
            bottleneck_result = analyze_thermal_bottlenecks(
                known_elements, heat_load_w=heat_load, topology=topology
            )
            partial_warnings = list(warnings)
            for warning in (
                "incomplete_thermal_network",
                "known_subpath_only_not_complete_junction_temperature",
                "one_dimensional_steady_engineering_estimate_not_cfd_or_experiment",
            ):
                if warning not in partial_warnings:
                    partial_warnings.append(warning)
            path_graph = build_thermal_path_graph({
                "topology": topology,
                "elements": known_elements,
                "node_temperatures": partial_nodes,
                "heat_load_w": heat_load,
                "partial_graph": True,
                "incomplete_network": True,
                "final_junction_node_present": False,
            })
            return _result(
                "partial_result",
                topology,
                heat_load_w=float(heat_load) if heat_load is not None else None,
                reference_temperature_c=float(reference) if reference is not None else None,
                elements=elements,
                node_temperatures=partial_nodes,
                bottlenecks=list(bottleneck_result.get("bottlenecks") or []),
                thermal_path_graph=path_graph,
                steps=[
                    "Resolve only the explicitly known thermal-resistance subpath.",
                    "Do not calculate a complete junction temperature while a required element is missing.",
                ],
                warnings=partial_warnings,
                missing_parameters=missing,
                assumptions=assumptions,
                partial_result=True,
                incomplete_network=True,
                known_resistance_subtotal_k_per_w=known_subtotal,
                known_temperature_rise_c=known_delta,
                known_elements=known_elements,
                missing_elements=missing_elements,
                completeness_ratio=len(known_elements) / len(elements) if elements else None,
            )
        return _result("missing_params", topology, heat_load_w=heat_load, reference_temperature_c=reference, allowable_total_resistance_k_per_w=allowed_total, elements=elements, missing_parameters=missing, assumptions=assumptions, warnings=warnings)

    junction = None
    node_temperatures: list[dict[str, Any]] = []
    steps = ["Resolve only explicit or fully specified element thermal resistances."]
    if total is not None:
        steps.append("Combine resistances using the declared series/parallel topology.")
    if total is not None and heat_load is not None and reference is not None:
        junction = float(reference) + float(heat_load) * total
        if topology == "series":
            node_temperatures = _node_temperatures(elements, float(heat_load), float(reference))
            steps.append("Starting at the reference boundary, accumulate Q*R toward the junction.")
        else:
            node_temperatures = [
                {"node_id": "reference", "name": "Reference boundary", "temperature_c": float(reference), "node_type": "reference"},
                {"node_id": "junction", "name": "Equivalent junction", "temperature_c": junction, "node_type": "junction"},
            ]
            steps.append("Apply Q*R_eq across the equivalent parallel network.")
    margin = float(allowable) - junction if allowable is not None and junction is not None else None
    if allowed_total is not None:
        steps.append("Calculate the allowable total resistance from the explicit junction limit.")
    warnings.append("one_dimensional_steady_engineering_estimate_not_cfd_or_experiment")
    bottleneck_result = analyze_thermal_bottlenecks(elements, heat_load_w=heat_load, topology=topology)
    path_graph = build_thermal_path_graph(
        {
            "topology": topology,
            "elements": elements,
            "node_temperatures": node_temperatures,
            "heat_load_w": heat_load,
        }
    )
    return _result(
        "success",
        topology,
        total_resistance_k_per_w=total,
        heat_load_w=float(heat_load) if heat_load is not None else None,
        reference_temperature_c=float(reference) if reference is not None else None,
        junction_temperature_c=junction,
        allowable_total_resistance_k_per_w=allowed_total,
        margin_c=margin,
        elements=elements,
        node_temperatures=node_temperatures,
        bottlenecks=list(bottleneck_result.get("bottlenecks") or []),
        thermal_path_graph=path_graph,
        steps=steps,
        warnings=warnings,
        assumptions=assumptions,
    )


def thermal_resistance_network_solve(**kwargs: Any) -> dict[str, Any]:
    result = solve_thermal_resistance_network(kwargs.get("network") or kwargs)
    payload = result.to_dict()
    return {
        "tool_name": "thermal_resistance_network_solve",
        "status": "ok" if result.status == "success" else "error",
        "thermal_network_status": result.status,
        "inputs": kwargs,
        "formula": result.formula,
        "calculation_steps": result.steps,
        "result": payload,
        "warnings": result.warnings,
        "assumptions": result.assumptions,
        "missing_parameters": result.missing_parameters,
        "error": result.error,
        "engineering_note": "One-dimensional steady thermal-resistance network estimate only; not CFD, experiment, or package simulation.",
    }


__all__ = [
    "THERMAL_NETWORK_FORMULA",
    "solve_thermal_resistance_network",
    "thermal_resistance_network_solve",
]
