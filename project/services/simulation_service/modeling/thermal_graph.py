from __future__ import annotations

from dataclasses import dataclass

from .model_ir import ModelIR
from .registry import ComponentRegistry


LINEAR_ELEMENT_TYPES = frozenset({
    "thermal_resistance", "conductive_layer", "convective_heat_transfer",
})


class _DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    def add(self, value: tuple[str, str]) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: tuple[str, str]) -> tuple[str, str]:
        self.add(value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


@dataclass(frozen=True)
class ThermalElementEdge:
    component_id: str
    component_type: str
    left_node: str
    right_node: str


@dataclass(frozen=True)
class ThermalGraph:
    port_nodes: dict[tuple[str, str], str]
    elements: tuple[ThermalElementEdge, ...]
    boundary_nodes: dict[str, str]

    @property
    def adjacency(self) -> dict[str, list[tuple[str, str]]]:
        result: dict[str, list[tuple[str, str]]] = {}
        for edge in self.elements:
            result.setdefault(edge.left_node, []).append((edge.right_node, edge.component_id))
            result.setdefault(edge.right_node, []).append((edge.left_node, edge.component_id))
        return result

    @property
    def degree(self) -> dict[str, int]:
        return {node: len(neighbors) for node, neighbors in self.adjacency.items()}


def build_thermal_graph(model: ModelIR, registry: ComponentRegistry | None = None) -> ThermalGraph:
    registry = registry or ComponentRegistry.default()
    components = {item.id: item for item in model.components}
    sets = _DisjointSet()
    for component in model.components:
        spec = registry.get(component.type)
        if spec is None:
            continue
        for port in spec.ports:
            sets.add((component.id, port.name))
    for connection in model.connections:
        left_component = components.get(connection.from_component)
        right_component = components.get(connection.to_component)
        left_spec = registry.get(left_component.type) if left_component else None
        right_spec = registry.get(right_component.type) if right_component else None
        if (
            left_spec is None or right_spec is None
            or left_spec.port(connection.from_port) is None
            or right_spec.port(connection.to_port) is None
        ):
            continue
        sets.union(
            (connection.from_component, connection.from_port),
            (connection.to_component, connection.to_port),
        )
    members: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for port in list(sets.parent):
        members.setdefault(sets.find(port), []).append(port)
    names = {
        root: "node_" + "__".join(f"{component}_{port}" for component, port in sorted(values))
        for root, values in members.items()
    }
    port_nodes = {port: names[sets.find(port)] for port in sets.parent}
    elements = tuple(
        ThermalElementEdge(
            component.id,
            component.type,
            port_nodes[(component.id, "A")],
            port_nodes[(component.id, "B")],
        )
        for component in model.components
        if component.type in LINEAR_ELEMENT_TYPES
        and (component.id, "A") in port_nodes
        and (component.id, "B") in port_nodes
    )
    boundary_nodes = {
        component.id: port_nodes[(component.id, "A" if component.type == "temperature_source" else "H")]
        for component in model.components
        if component.type in {"temperature_source", "thermal_reference"}
        and (component.id, "A" if component.type == "temperature_source" else "H") in port_nodes
    }
    return ThermalGraph(port_nodes, elements, boundary_nodes)


def reachable_nodes(graph: ThermalGraph, start: str) -> set[str]:
    adjacency = graph.adjacency
    visited: set[str] = set()
    pending = [start]
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        pending.extend(peer for peer, _component_id in adjacency.get(node, ()) if peer not in visited)
    return visited


__all__ = [
    "LINEAR_ELEMENT_TYPES", "ThermalElementEdge", "ThermalGraph", "build_thermal_graph",
    "reachable_nodes",
]
