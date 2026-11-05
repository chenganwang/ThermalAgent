from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .model_ir import ModelIR


def _connection(left: str, left_port: str, right: str, right_port: str) -> dict[str, str]:
    return {
        "from_component": left, "from_port": left_port,
        "to_component": right, "to_port": right_port,
    }


def with_requested_outputs(
    model: ModelIR,
    requested_outputs: Sequence[Mapping[str, Any]],
) -> ModelIR:
    """Return the same logical network with a closed, server-owned output list."""

    payload = model.to_dict()
    outputs = [dict(item) for item in requested_outputs]
    payload["requested_outputs"] = outputs
    if any(str(item.get("type") or "") == "temperature" for item in outputs):
        if not any(item.get("type") == "thermal_reference" for item in payload["components"]):
            payload["components"].append({
                "id": "measurement_reference", "type": "thermal_reference", "parameters": {},
            })
    payload["simulation_options"]["max_result_signals"] = max(
        int(payload["simulation_options"].get("max_result_signals") or 0), len(outputs),
    )
    return ModelIR.from_dict(payload)


def build_branched_network(
    *,
    model_id: str,
    upstream_resistances_k_w: Sequence[float],
    branch_resistances_k_w: Sequence[Sequence[float]],
    downstream_resistances_k_w: Sequence[float],
    hot_temperature_k: float,
    cold_temperature_k: float,
) -> ModelIR:
    """Build the bounded V1 series -> parallel paths -> merge -> series family."""

    upstream = [float(value) for value in upstream_resistances_k_w]
    branches = [[float(value) for value in branch] for branch in branch_resistances_k_w]
    downstream = [float(value) for value in downstream_resistances_k_w]
    components: list[dict[str, object]] = [
        {
            "id": "hot_boundary", "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(hot_temperature_k), "unit": "K"}},
        },
    ]
    for prefix, values in (("upstream", upstream), ("downstream", downstream)):
        components.extend(
            {
                "id": f"{prefix}_{index}", "type": "thermal_resistance",
                "parameters": {"resistance_k_w": {"value": value, "unit": "K/W"}},
            }
            for index, value in enumerate(values, start=1)
        )
    for branch_index, values in enumerate(branches, start=1):
        components.extend(
            {
                "id": f"branch_{branch_index}_{element_index}", "type": "thermal_resistance",
                "parameters": {"resistance_k_w": {"value": value, "unit": "K/W"}},
            }
            for element_index, value in enumerate(values, start=1)
        )
    components.extend((
        {
            "id": "cold_boundary", "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(cold_temperature_k), "unit": "K"}},
        },
        {"id": "solver_configuration_1", "type": "solver_configuration", "parameters": {}},
    ))
    connections: list[dict[str, str]] = []
    previous_id, previous_port = "hot_boundary", "A"
    for index in range(1, len(upstream) + 1):
        component_id = f"upstream_{index}"
        connections.append(_connection(previous_id, previous_port, component_id, "A"))
        previous_id, previous_port = component_id, "B"
    split_id, split_port = previous_id, previous_port
    merge_id, merge_port = (
        ("downstream_1", "A") if downstream else ("cold_boundary", "A")
    )
    for branch_index, values in enumerate(branches, start=1):
        previous_id, previous_port = split_id, split_port
        for element_index in range(1, len(values) + 1):
            component_id = f"branch_{branch_index}_{element_index}"
            connections.append(_connection(previous_id, previous_port, component_id, "A"))
            previous_id, previous_port = component_id, "B"
        if values:
            connections.append(_connection(previous_id, previous_port, merge_id, merge_port))
    if downstream:
        for index in range(1, len(downstream)):
            connections.append(_connection(f"downstream_{index}", "B", f"downstream_{index + 1}", "A"))
        connections.append(_connection(f"downstream_{len(downstream)}", "B", "cold_boundary", "A"))
    connections.append(_connection("solver_configuration_1", "network", "cold_boundary", "A"))
    output_source = "upstream_1" if upstream else "branch_1_1"
    return ModelIR.from_dict({
        "schema_version": "1.0", "model_id": str(model_id), "model_domain": "thermal",
        "components": components, "connections": connections, "parameters": {},
        "boundary_conditions": [
            {"component_id": "hot_boundary", "kind": "temperature"},
            {"component_id": "cold_boundary", "kind": "temperature"},
        ],
        "requested_outputs": [
            {
                "id": "source_heat_flow", "type": "heat_flow",
                "source_component_id": output_source, "source_port": "A",
            },
        ],
        "simulation_options": {"stop_time_s": 10.0, "max_result_signals": 8},
    })


def build_series_network(
    *,
    model_id: str,
    resistances_k_w: Sequence[float],
    hot_temperature_k: float,
    cold_temperature_k: float,
) -> ModelIR:
    """Build one generic steady series network from an arbitrary resistor sequence."""

    resistances = [float(value) for value in resistances_k_w]
    components: list[dict[str, object]] = [
        {
            "id": "hot_boundary",
            "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(hot_temperature_k), "unit": "K"}},
        },
        *[
            {
                "id": f"resistance_{index}",
                "type": "thermal_resistance",
                "parameters": {"resistance_k_w": {"value": value, "unit": "K/W"}},
            }
            for index, value in enumerate(resistances, start=1)
        ],
        {
            "id": "cold_boundary",
            "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(cold_temperature_k), "unit": "K"}},
        },
        {"id": "solver_configuration_1", "type": "solver_configuration", "parameters": {}},
    ]
    chain = ["hot_boundary", *[f"resistance_{index}" for index in range(1, len(resistances) + 1)], "cold_boundary"]
    connections: list[dict[str, str]] = []
    for index in range(len(chain) - 1):
        left = chain[index]
        right = chain[index + 1]
        connections.append({
            "from_component": left,
            "from_port": "A" if left == "hot_boundary" else "B",
            "to_component": right,
            "to_port": "A",
        })
    connections.append({
        "from_component": "solver_configuration_1",
        "from_port": "network",
        "to_component": "cold_boundary",
        "to_port": "A",
    })
    return ModelIR.from_dict({
        "schema_version": "1.0",
        "model_id": str(model_id),
        "model_domain": "thermal",
        "components": components,
        "connections": connections,
        "parameters": {},
        "boundary_conditions": [
            {"component_id": "hot_boundary", "kind": "temperature"},
            {"component_id": "cold_boundary", "kind": "temperature"},
        ],
        "requested_outputs": [
            {
                "id": "source_heat_flow",
                "type": "heat_flow",
                "source_component_id": "resistance_1",
            }
        ] if resistances else [],
        "simulation_options": {"stop_time_s": 10.0, "max_result_signals": 8},
    })


def build_layered_network(
    *,
    model_id: str,
    layers: Sequence[dict[str, float]],
    hot_temperature_k: float,
    cold_temperature_k: float,
) -> ModelIR:
    """Build a physical layer chain without collapsing its L/k/A parameters."""

    normalized_layers = [dict(item) for item in layers]
    components: list[dict[str, object]] = [
        {
            "id": "hot_boundary",
            "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(hot_temperature_k), "unit": "K"}},
        },
        *[
            {
                "id": f"layer_{index}",
                "type": "conductive_layer",
                "parameters": {
                    "thickness_m": {"value": float(layer["thickness_m"]), "unit": "m"},
                    "conductivity_w_mk": {
                        "value": float(layer["conductivity_w_mk"]), "unit": "W/(m*K)",
                    },
                    "area_m2": {"value": float(layer["area_m2"]), "unit": "m^2"},
                },
            }
            for index, layer in enumerate(normalized_layers, start=1)
        ],
        {
            "id": "cold_boundary",
            "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(cold_temperature_k), "unit": "K"}},
        },
        {"id": "solver_configuration_1", "type": "solver_configuration", "parameters": {}},
    ]
    chain = ["hot_boundary", *[f"layer_{index}" for index in range(1, len(normalized_layers) + 1)], "cold_boundary"]
    connections = [
        {
            "from_component": chain[index],
            "from_port": "A" if chain[index] == "hot_boundary" else "B",
            "to_component": chain[index + 1],
            "to_port": "A",
        }
        for index in range(len(chain) - 1)
    ]
    connections.append({
        "from_component": "solver_configuration_1", "from_port": "network",
        "to_component": "cold_boundary", "to_port": "A",
    })
    return ModelIR.from_dict({
        "schema_version": "1.0",
        "model_id": str(model_id),
        "model_domain": "thermal",
        "components": components,
        "connections": connections,
        "parameters": {},
        "boundary_conditions": [
            {"component_id": "hot_boundary", "kind": "temperature"},
            {"component_id": "cold_boundary", "kind": "temperature"},
        ],
        "requested_outputs": [
            {"id": "source_heat_flow", "type": "heat_flow", "source_component_id": "layer_1"},
        ] if normalized_layers else [],
        "simulation_options": {"stop_time_s": 10.0, "max_result_signals": 8},
    })


def build_conduction_convection_network(
    *,
    model_id: str,
    resistances_k_w: Sequence[float],
    convection_coefficient_w_m2k: float,
    convection_area_m2: float,
    hot_temperature_k: float,
    ambient_temperature_k: float,
) -> ModelIR:
    """Build a linear conduction chain terminated by a reviewed convection element."""

    resistances = [float(value) for value in resistances_k_w]
    element_ids = [f"resistance_{index}" for index in range(1, len(resistances) + 1)] + ["convection_1"]
    components: list[dict[str, object]] = [
        {
            "id": "hot_boundary", "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(hot_temperature_k), "unit": "K"}},
        },
        *[
            {
                "id": component_id, "type": "thermal_resistance",
                "parameters": {"resistance_k_w": {"value": value, "unit": "K/W"}},
            }
            for component_id, value in zip(element_ids, resistances)
        ],
        {
            "id": "convection_1", "type": "convective_heat_transfer",
            "parameters": {
                "area_m2": {"value": float(convection_area_m2), "unit": "m^2"},
                "heat_transfer_coefficient_w_m2k": {
                    "value": float(convection_coefficient_w_m2k), "unit": "W/(m^2*K)",
                },
            },
        },
        {
            "id": "ambient_boundary", "type": "temperature_source",
            "parameters": {"temperature_k": {"value": float(ambient_temperature_k), "unit": "K"}},
        },
        {"id": "solver_configuration_1", "type": "solver_configuration", "parameters": {}},
    ]
    chain = ["hot_boundary", *element_ids, "ambient_boundary"]
    connections = [
        {
            "from_component": chain[index],
            "from_port": "A" if chain[index] == "hot_boundary" else "B",
            "to_component": chain[index + 1],
            "to_port": "A",
        }
        for index in range(len(chain) - 1)
    ]
    connections.append({
        "from_component": "solver_configuration_1", "from_port": "network",
        "to_component": "ambient_boundary", "to_port": "A",
    })
    output_source = element_ids[0]
    return ModelIR.from_dict({
        "schema_version": "1.0", "model_id": str(model_id), "model_domain": "thermal",
        "components": components, "connections": connections, "parameters": {},
        "boundary_conditions": [
            {"component_id": "hot_boundary", "kind": "temperature"},
            {"component_id": "ambient_boundary", "kind": "temperature", "role": "ambient"},
        ],
        "requested_outputs": [
            {"id": "source_heat_flow", "type": "heat_flow", "source_component_id": output_source},
        ],
        "simulation_options": {
            "stop_time_s": 10.0, "max_result_signals": 8, "convection_model": "linear",
        },
    })


__all__ = [
    "build_branched_network", "build_conduction_convection_network", "build_layered_network",
    "build_series_network", "with_requested_outputs",
]
