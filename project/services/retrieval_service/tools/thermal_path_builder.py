from __future__ import annotations

from copy import deepcopy
from typing import Any


def _node_type(element: dict[str, Any]) -> str:
    value = str(element.get("element_type") or "node").lower()
    return value if value in {"chip", "package", "tim", "cold_plate", "coolant", "ambient", "node"} else "node"


def build_thermal_path_graph(solve_result: dict[str, Any] | None) -> dict[str, Any]:
    data = deepcopy(solve_result or {})
    elements = list(data.get("elements") or [])
    topology = str(data.get("topology") or "unknown")
    if topology == "mixed":
        # Flattened leaf elements do not retain nested connectivity. Rendering
        # them as a series path would invent a different physical network.
        return {"generated": False, "graph_type": "thermal_resistance_network", "nodes": [], "edges": [],
                "warnings": ["mixed_network_graph_requires_explicit_nested_connectivity"], "cfd_executed": False}
    temperatures = {
        str(row.get("node_id")): row.get("temperature_c")
        for row in list(data.get("node_temperatures") or [])
        if isinstance(row, dict) and row.get("node_id")
    }
    heat_load = data.get("heat_load_w")
    reference_temperature = temperatures.get("reference")
    nodes: list[dict[str, Any]] = [
        {
            "id": "reference",
            "label": "Reference boundary",
            "type": "ambient",
            "temperature_c": reference_temperature,
        }
    ]
    edges: list[dict[str, Any]] = []

    if topology == "parallel":
        junction_temperature = temperatures.get("junction")
        nodes.append({"id": "junction", "label": "Equivalent junction", "type": "chip", "temperature_c": junction_temperature})
        total_conductance = sum(
            1.0 / float(row["resistance_k_per_w"])
            for row in elements
            if row.get("resistance_k_per_w") is not None and float(row["resistance_k_per_w"]) > 0
        )
        for element in elements:
            resistance = element.get("resistance_k_per_w")
            branch_heat = None
            if heat_load is not None and resistance is not None and total_conductance > 0:
                branch_heat = float(heat_load) * (1.0 / float(resistance)) / total_conductance
            edges.append(
                {
                    "source": "reference",
                    "target": "junction",
                    "label": element.get("name") or element.get("element_id"),
                    "element_id": element.get("element_id"),
                    "resistance_k_per_w": resistance,
                    "delta_t_c": None if branch_heat is None or resistance is None else branch_heat * float(resistance),
                    "heat_flow_w": branch_heat,
                }
            )
    else:
        previous = "reference"
        for element in elements:
            element_id = str(element.get("element_id") or f"element_{len(edges) + 1}")
            target = f"after_{element_id}"
            resistance = element.get("resistance_k_per_w")
            nodes.append(
                {
                    "id": target,
                    "label": element.get("name") or element_id,
                    "type": _node_type(element),
                    "temperature_c": temperatures.get(target),
                }
            )
            edges.append(
                {
                    "source": previous,
                    "target": target,
                    "label": element.get("name") or element_id,
                    "element_id": element_id,
                    "resistance_k_per_w": resistance,
                    "delta_t_c": None if heat_load is None or resistance is None else float(heat_load) * float(resistance),
                    "heat_flow_w": float(heat_load) if heat_load is not None else None,
                }
            )
            previous = target

    for edge in edges:
        if edge.get("heat_flow_w") is not None and edge["heat_flow_w"] > 0:
            # Solver temperatures accumulate outwards from the cold reference.
            # Positive heat flows in the opposite direction, towards it.
            edge["source"], edge["target"] = edge["target"], edge["source"]
            edge["direction"] = "heat_flow_hot_to_cold"
            edge["description"] = "正热负荷下由高温节点流向低温参考边界。"
        else:
            edge["direction"] = "declared_connection"
            edge["description"] = "仅表示声明连接，未计算热流方向。"

    return {
        "generated": bool(elements),
        "graph_type": "thermal_resistance_network",
        "nodes": nodes,
        "edges": edges,
        "partial_graph": bool(data.get("partial_graph")),
        "incomplete_network": bool(data.get("incomplete_network")),
        "final_junction_node_present": bool(
            data.get("final_junction_node_present", bool(elements) and not data.get("partial_graph"))
        ),
        "warnings": [
            "schematic_thermal_path_not_solver_output",
            "箭头有热流值时表示高温至低温；无热流值时仅表示声明连接。",
            "串联节点温度按输入元件顺序从参考边界累计；不是实际部件表面测量。",
            *(["incomplete_thermal_network"] if data.get("partial_graph") else []),
        ],
        "cfd_executed": False,
    }


__all__ = ["build_thermal_path_graph"]
