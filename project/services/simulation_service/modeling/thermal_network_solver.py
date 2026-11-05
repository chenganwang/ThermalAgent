from __future__ import annotations

from math import isfinite
from typing import Any

from .model_ir import IRComponent, ModelIR, ParameterValue
from .registry import ComponentRegistry


_LINEAR_ELEMENT_TYPES = frozenset({
    "thermal_resistance", "conductive_layer", "convective_heat_transfer",
})


class _DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    def add(self, value: tuple[str, str]) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: tuple[str, str]) -> tuple[str, str]:
        self.add(value)
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


class ThermalNetworkReferenceSolver:
    """Independent bounded steady linear thermal-network reference solver.

    The implementation consumes logical Model IR only. It does not import or
    call the compiler, MATLAB, Simulink, or Simscape.
    """

    solver_version = "thermal-network-reference-v1"

    def __init__(self, *, max_unknown_nodes: int = 64) -> None:
        self.max_unknown_nodes = max(int(max_unknown_nodes), 1)

    def solve(self, model: ModelIR) -> dict[str, Any]:
        if any(item.type == "thermal_mass" for item in model.components):
            return self._not_applicable("Transient thermal-mass networks are outside the steady reference solver.")
        if any(item.type not in _supported_component_types() for item in model.components):
            return self._not_applicable("The network contains a component outside the linear steady allowlist.")
        if str(model.simulation_options.get("convection_model") or "linear").casefold() != "linear":
            return self._not_applicable("Nonlinear convection is outside the linear steady reference solver.")

        graph = _logical_nodes(model)
        elements: list[tuple[IRComponent, str, str, float]] = []
        for component in model.components:
            if component.type not in _LINEAR_ELEMENT_TYPES:
                continue
            resistance = _component_resistance(component)
            if resistance is None:
                return self._failure("REFERENCE_PARAMETER_INVALID", f"Invalid parameters for {component.id}.")
            left = graph["port_nodes"].get((component.id, "A"))
            right = graph["port_nodes"].get((component.id, "B"))
            if left is None or right is None or left == right:
                return self._failure("REFERENCE_TOPOLOGY_INVALID", f"Invalid element endpoints for {component.id}.")
            elements.append((component, left, right, resistance))
        if not elements:
            return self._not_applicable("No supported steady resistance element exists.")

        fixed: dict[str, float] = {}
        for component in model.components:
            if component.type == "temperature_source":
                node = graph["port_nodes"].get((component.id, "A"))
                value = _temperature_k(component.parameters.get("temperature_k"))
            elif component.type == "thermal_reference":
                node = graph["port_nodes"].get((component.id, "H"))
                value = 0.0
            else:
                continue
            if node is None or value is None:
                return self._failure("REFERENCE_BOUNDARY_INVALID", f"Invalid boundary {component.id}.")
            if node in fixed and abs(fixed[node] - value) > 1e-9:
                return self._failure("REFERENCE_BOUNDARY_CONFLICT", "Incompatible temperatures share one node.")
            fixed[node] = value
        if len(fixed) < 2:
            return self._not_applicable("At least two distinct fixed-temperature nodes are required.")

        element_nodes = {node for _item, left, right, _resistance in elements for node in (left, right)}
        unknown = sorted(element_nodes - set(fixed))
        if len(unknown) > self.max_unknown_nodes:
            return self._failure("REFERENCE_RESOURCE_LIMIT", "The reference matrix exceeds its node limit.")
        index = {node: position for position, node in enumerate(unknown)}
        matrix = [[0.0 for _ in unknown] for _ in unknown]
        vector = [0.0 for _ in unknown]
        for _component, left, right, resistance in elements:
            conductance = 1.0 / resistance
            for node, peer in ((left, right), (right, left)):
                if node not in index:
                    continue
                row = index[node]
                matrix[row][row] += conductance
                if peer in index:
                    matrix[row][index[peer]] -= conductance
                elif peer in fixed:
                    vector[row] += conductance * fixed[peer]
                else:
                    return self._failure("REFERENCE_FLOATING_NODE", "A thermal node has no boundary path.")
        try:
            solved_values = _solve_linear(matrix, vector)
        except ValueError:
            return self._failure("REFERENCE_SINGULAR_NETWORK", "The thermal network is singular or disconnected.")
        temperatures = dict(fixed)
        temperatures.update({node: solved_values[position] for node, position in index.items()})
        if any(not isfinite(value) for value in temperatures.values()):
            return self._failure("REFERENCE_NON_FINITE", "The thermal reference solution is non-finite.")

        component_flows = {
            component.id: (temperatures[left] - temperatures[right]) / resistance
            for component, left, right, resistance in elements
        }
        degree: dict[str, int] = {}
        for _component, left, right, _resistance in elements:
            degree[left] = degree.get(left, 0) + 1
            degree[right] = degree.get(right, 0) + 1
        branched = any(value > 2 for value in degree.values())
        if branched:
            method = "NODAL_LINEAR"
        elif any(component.type == "conductive_layer" for component, *_rest in elements):
            method = "LAYERED_CONDUCTION"
        elif any(component.type == "convective_heat_transfer" for component, *_rest in elements):
            method = "NODAL_LINEAR"
        else:
            method = "SERIES_RESISTANCE"
        first_flow = abs(next(iter(component_flows.values())))
        port_nodes = graph["port_nodes"]
        expected_outputs: dict[str, dict[str, Any]] = {}
        component_types = {item.id: item.type for item in model.components}
        for requested in model.requested_outputs:
            if requested.type == "heat_flow" and requested.source_component_id in component_flows:
                expected_outputs[requested.id] = {
                    "value": abs(component_flows[requested.source_component_id]),
                    "unit": "W",
                    "quantity": "heat_flow_rate",
                }
            elif requested.type == "temperature":
                default_port = {
                    "temperature_source": "A", "thermal_mass": "M",
                    "thermal_resistance": "B", "conductive_layer": "B",
                    "convective_heat_transfer": "B",
                }.get(component_types.get(requested.source_component_id, ""), "")
                port = requested.source_port or default_port
                node = port_nodes.get((requested.source_component_id, port))
                if node in temperatures:
                    expected_outputs[requested.id] = {
                        "value": temperatures[node], "unit": "K", "quantity": "temperature",
                    }
        return {
            "solver_version": self.solver_version,
            "status": "PASS",
            "validation_method": method,
            "heat_flow_w": first_flow,
            "node_temperatures_k": {key: temperatures[key] for key in sorted(temperatures)},
            "component_heat_flows_w": component_flows,
            "expected_outputs": expected_outputs,
            "port_nodes": {
                f"{component_id}.{port}": node
                for (component_id, port), node in sorted(graph["port_nodes"].items())
            },
            "reason": "independent_linear_steady_nodal_solution",
        }

    def _not_applicable(self, reason: str) -> dict[str, Any]:
        return {
            "solver_version": self.solver_version,
            "status": "NOT_APPLICABLE",
            "validation_method": "BASIC_ONLY",
            "reason": reason,
        }

    def _failure(self, code: str, reason: str) -> dict[str, Any]:
        return {
            "solver_version": self.solver_version,
            "status": "FAIL",
            "validation_method": "BASIC_ONLY",
            "code": code,
            "reason": reason,
        }


def _supported_component_types() -> frozenset[str]:
    return frozenset({
        *_LINEAR_ELEMENT_TYPES,
        "temperature_source", "thermal_reference", "solver_configuration",
    })


def _logical_nodes(model: ModelIR) -> dict[str, Any]:
    registry = ComponentRegistry.default()
    components = {item.id: item for item in model.components}
    sets = _DisjointSet()
    for component in model.components:
        spec = registry.get(component.type)
        if spec is None:
            continue
        for port in spec.ports:
            sets.add((component.id, port.name))
    for edge in model.connections:
        if edge.from_component in components and edge.to_component in components:
            sets.union(
                (edge.from_component, edge.from_port),
                (edge.to_component, edge.to_port),
            )
    members: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for port in sets.parent:
        members.setdefault(sets.find(port), []).append(port)
    names = {
        root: "node_" + "__".join(f"{component}_{port}" for component, port in sorted(values))
        for root, values in members.items()
    }
    return {
        "port_nodes": {port: names[sets.find(port)] for port in sets.parent},
    }


def _component_resistance(component: IRComponent) -> float | None:
    if component.type == "thermal_resistance":
        return _positive(component.parameters.get("resistance_k_w"), "K/W")
    if component.type == "conductive_layer":
        thickness = _positive(component.parameters.get("thickness_m"), "m")
        conductivity = _positive(component.parameters.get("conductivity_w_mk"), "W/(m*K)")
        area = _positive(component.parameters.get("area_m2"), "m^2")
        if thickness is None or conductivity is None or area is None:
            return None
        return thickness / (conductivity * area)
    if component.type == "convective_heat_transfer":
        area = _positive(component.parameters.get("area_m2"), "m^2")
        coefficient = _positive(
            component.parameters.get("heat_transfer_coefficient_w_m2k"), "W/(m^2*K)",
        )
        if area is None or coefficient is None:
            return None
        return 1.0 / (area * coefficient)
    return None


def _positive(parameter: ParameterValue | None, unit: str) -> float | None:
    if parameter is None or parameter.unit != unit or isinstance(parameter.value, bool):
        return None
    if not isinstance(parameter.value, (int, float)):
        return None
    value = float(parameter.value)
    return value if isfinite(value) and value > 0.0 else None


def _temperature_k(parameter: ParameterValue | None) -> float | None:
    if parameter is None or isinstance(parameter.value, bool) or not isinstance(parameter.value, (int, float)):
        return None
    value = float(parameter.value)
    if parameter.unit in {"degC", "°C"}:
        value += 273.15
    elif parameter.unit != "K":
        return None
    return value if isfinite(value) and value > 0.0 else None


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    if size == 0:
        return []
    augmented = [list(row) + [float(vector[index])] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-14:
            raise ValueError("singular matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0.0:
                continue
            augmented[row] = [
                left - factor * right
                for left, right in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


__all__ = ["ThermalNetworkReferenceSolver"]
