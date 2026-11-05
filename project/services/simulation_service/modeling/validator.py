from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
import re
from typing import Any, Protocol

from .model_ir import ModelIR
from .output_registry import OutputRegistry
from .registry import ComponentRegistry
from .thermal_graph import build_thermal_graph, reachable_nodes


_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_TOP_LEVEL_FIELDS = frozenset({
    "schema_version", "model_id", "model_domain", "components", "connections", "parameters",
    "boundary_conditions", "requested_outputs", "simulation_options",
})


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    severity: str = "error"
    validator: str = ""


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    normalized_parameters: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.issues)

    def add(self, code: str, message: str, *, path: str = "", validator: str = "") -> None:
        self.issues.append(ValidationIssue(code, message, path, "error", validator))

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": [asdict(item) for item in self.issues], "normalized_parameters": self.normalized_parameters}


@dataclass(frozen=True)
class ValidationLimits:
    max_components: int = 64
    max_connections: int = 128
    max_simulation_time_s: float = 3600.0
    max_result_signals: int = 32
    max_branches: int = 8


_VALIDATION_SEAL = object()


class ValidatedModelIR:
    """A validator-issued, hash-bound capability token for compilation."""

    __slots__ = ("model_ir", "report", "model_ir_hash", "_seal")

    def __init__(self, model_ir: ModelIR, report: ValidationReport, *, _seal: object) -> None:
        if _seal is not _VALIDATION_SEAL or not report.valid:
            raise TypeError("ValidatedModelIR can only be issued by ModelValidator")
        self.model_ir = model_ir
        self.report = report
        self.model_ir_hash = model_ir.digest()
        self._seal = _seal

    @property
    def authentic(self) -> bool:
        return self._seal is _VALIDATION_SEAL and self.report.valid and self.model_ir.digest() == self.model_ir_hash


class ModelValidationError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("Model IR validation failed")
        self.report = report


class ValidatorLayer(Protocol):
    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None: ...


class SchemaValidator:
    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        if model.schema_version != "1.0":
            report.add("SCHEMA_VERSION_UNSUPPORTED", "Unsupported Model IR schema version.", path="schema_version", validator=type(self).__name__)
        missing = sorted(_TOP_LEVEL_FIELDS - set(model.source_payload))
        if missing:
            report.add("SCHEMA_FIELD_MISSING", "Required Model IR fields are missing.", path=",".join(missing), validator=type(self).__name__)
        unknown = sorted(set(model.source_payload) - _TOP_LEVEL_FIELDS)
        if unknown:
            report.add("SCHEMA_UNKNOWN_FIELD", "Unknown Model IR fields are not accepted.", path=",".join(unknown), validator=type(self).__name__)
        if not model.components:
            report.add("COMPONENTS_REQUIRED", "At least one component is required.", path="components", validator=type(self).__name__)


class RegistryValidator:
    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        for index, component in enumerate(model.components):
            if registry.get(component.type) is None:
                report.add("UNSUPPORTED_COMPONENT", "Component type is not allowlisted.", path=f"components[{index}].type", validator=type(self).__name__)


class ParameterValidator:
    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        for component in model.components:
            spec = registry.get(component.type)
            if spec is None:
                continue
            unknown = sorted(set(component.parameters) - {item.name for item in spec.parameters})
            for name in unknown:
                report.add("UNKNOWN_PARAMETER", "Parameter is not allowlisted for the component.", path=f"components.{component.id}.parameters.{name}", validator=type(self).__name__)
            for parameter in spec.parameters:
                value = component.parameters.get(parameter.name)
                if value is None:
                    if parameter.required and parameter.default is None:
                        report.add("MISSING_PARAMETER", "Required component parameter is missing.", path=f"components.{component.id}.parameters.{parameter.name}", validator=type(self).__name__)
                    continue
                if parameter.value_type == "number":
                    if isinstance(value.value, bool) or not isinstance(value.value, (int, float)) or not isfinite(float(value.value)):
                        report.add("PARAMETER_NOT_FINITE", "Parameter must be a finite number.", path=f"components.{component.id}.parameters.{parameter.name}.value", validator=type(self).__name__)
                        continue


class UnitValidator:
    _factors = {("g", "kg"): 0.001, ("cm^2", "m^2"): 0.0001}

    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        for component in model.components:
            spec = registry.get(component.type)
            if spec is None:
                continue
            normalized: dict[str, float] = {}
            for name, value in component.parameters.items():
                parameter = spec.parameter(name)
                if parameter is None:
                    continue
                if value.unit not in parameter.accepted_units:
                    report.add("UNIT_NOT_ALLOWED", "Parameter unit is incompatible.", path=f"components.{component.id}.parameters.{name}.unit", validator=type(self).__name__)
                    continue
                if isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
                    numeric = float(value.value)
                    if value.unit in {"degC", "°C"} and parameter.canonical_unit == "K":
                        numeric += 273.15
                    else:
                        numeric *= self._factors.get((value.unit, parameter.canonical_unit), 1.0)
                    normalized[name] = numeric
                    if parameter.minimum is not None and numeric <= parameter.minimum:
                        report.add(
                            "PARAMETER_OUT_OF_RANGE",
                            "Parameter must be greater than its canonical minimum.",
                            path=f"components.{component.id}.parameters.{name}.value",
                            validator=type(self).__name__,
                        )
                    if parameter.maximum is not None and numeric > parameter.maximum:
                        report.add(
                            "PARAMETER_OUT_OF_RANGE",
                            "Parameter exceeds its canonical maximum.",
                            path=f"components.{component.id}.parameters.{name}.value",
                            validator=type(self).__name__,
                        )
            report.normalized_parameters[component.id] = normalized


class TopologyValidator:
    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        ids = [item.id for item in model.components]
        if len(ids) != len(set(ids)):
            report.add("DUPLICATE_COMPONENT_ID", "Component IDs must be unique.", path="components", validator=type(self).__name__)
        components = {item.id: item for item in model.components}
        connected: set[tuple[str, str]] = set()
        measurement_references = _measurement_reference_ids(model)
        for index, connection in enumerate(model.connections):
            left = components.get(connection.from_component)
            right = components.get(connection.to_component)
            if left is None or right is None:
                report.add("UNKNOWN_CONNECTION_COMPONENT", "Connection references an unknown component.", path=f"connections[{index}]", validator=type(self).__name__)
                continue
            left_spec, right_spec = registry.get(left.type), registry.get(right.type)
            left_port = left_spec.port(connection.from_port) if left_spec else None
            right_port = right_spec.port(connection.to_port) if right_spec else None
            if left_port is None or right_port is None:
                report.add("UNKNOWN_PORT", "Connection references an unknown port.", path=f"connections[{index}]", validator=type(self).__name__)
                continue
            if left.id == right.id:
                report.add("SELF_CONNECTION_FORBIDDEN", "Self-connections are not supported.", path=f"connections[{index}]", validator=type(self).__name__)
            if left_port.domain != "any_conserving" and right_port.domain != "any_conserving" and left_port.domain != right_port.domain:
                report.add("INCOMPATIBLE_PORT_DOMAIN", "Connection ports belong to incompatible physical domains.", path=f"connections[{index}]", validator=type(self).__name__)
            connected.update(((left.id, left_port.name), (right.id, right_port.name)))
        for component in model.components:
            spec = registry.get(component.type)
            if spec is None:
                continue
            if component.id in measurement_references:
                continue
            if not any(item[0] == component.id for item in connected):
                report.add("ISOLATED_COMPONENT", "Component is isolated.", path=f"components.{component.id}", validator=type(self).__name__)
            for port in spec.ports:
                if port.required and (component.id, port.name) not in connected:
                    report.add("UNCONNECTED_REQUIRED_PORT", "Required component port is unconnected.", path=f"components.{component.id}.ports.{port.name}", validator=type(self).__name__)


class ThermalGraphValidator:
    def __init__(self, limits: ValidationLimits) -> None:
        self.limits = limits

    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        seen_connections: set[tuple[tuple[str, str], tuple[str, str]]] = set()
        for index, connection in enumerate(model.connections):
            endpoints = tuple(sorted((
                (connection.from_component, connection.from_port),
                (connection.to_component, connection.to_port),
            )))
            if endpoints in seen_connections:
                report.add(
                    "DUPLICATE_CONNECTION", "Duplicate physical connections are forbidden.",
                    path=f"connections[{index}]", validator=type(self).__name__,
                )
            seen_connections.add(endpoints)
        graph = build_thermal_graph(model, registry)
        if not graph.elements:
            return
        for edge in graph.elements:
            if edge.left_node == edge.right_node:
                report.add(
                    "INVALID_BRANCH_MERGE",
                    "A linear thermal element cannot return to the same physical node.",
                    path=f"components.{edge.component_id}", validator=type(self).__name__,
                )
        component_types = {item.id: item.type for item in model.components}
        temperature_source_nodes = {
            node for component_id, node in graph.boundary_nodes.items()
            if component_types.get(component_id) == "temperature_source"
        }
        boundary_nodes = (
            temperature_source_nodes
            if len(temperature_source_nodes) >= 2
            else set(graph.boundary_nodes.values())
        )
        temperatures_by_node: dict[str, list[float]] = {}
        for component_id, node in graph.boundary_nodes.items():
            component_type = component_types.get(component_id)
            if component_type == "temperature_source":
                value = report.normalized_parameters.get(component_id, {}).get("temperature_k")
            elif component_type == "thermal_reference":
                value = 0.0
            else:
                value = None
            if value is not None:
                temperatures_by_node.setdefault(node, []).append(float(value))
        if any(values and max(values) - min(values) > 1e-9 for values in temperatures_by_node.values()):
            report.add(
                "MULTIPLE_INCOMPATIBLE_BOUNDARIES",
                "Different fixed temperatures cannot be imposed on one physical node.",
                validator=type(self).__name__,
            )
        if boundary_nodes:
            reached = reachable_nodes(graph, next(iter(boundary_nodes)))
            element_nodes = {
                node for edge in graph.elements for node in (edge.left_node, edge.right_node)
            }
            if not element_nodes.issubset(reached):
                report.add(
                    "DISCONNECTED_SUBGRAPH", "All thermal elements must belong to one boundary-connected graph.",
                    validator=type(self).__name__,
                )
            if len(boundary_nodes & reached) < 2:
                report.add(
                    "BOUNDARY_NOT_REACHABLE", "Every steady thermal graph requires two reachable boundaries.",
                    validator=type(self).__name__,
                )
        degree = graph.degree
        for node in boundary_nodes:
            if degree.get(node, 0) > 1:
                report.add(
                    "UNSUPPORTED_BRANCHING_PATTERN",
                    "The bounded V1 branch family cannot split or merge at a boundary node.",
                    validator=type(self).__name__,
                )
        junctions = sorted(node for node, value in degree.items() if value > 2)
        if not junctions:
            return
        valid_shape, branch_count = _bounded_branch_shape(graph, junctions)
        if not valid_shape:
            report.add(
                "UNSUPPORTED_BRANCHING_PATTERN",
                "Only one bounded split/merge branch family is supported.",
                validator=type(self).__name__,
            )
        if branch_count > self.limits.max_branches:
            report.add(
                "RESOURCE_LIMIT_BRANCHES", "Thermal branch count exceeds the configured limit.",
                validator=type(self).__name__,
            )


class BoundaryConditionValidator:
    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        ids = {item.id for item in model.components}
        component_types = {item.id: item.type for item in model.components}
        temperature_boundaries = {
            str(item.get("component_id") or "")
            for item in model.boundary_conditions
            if str(item.get("kind") or "").casefold() == "temperature"
            and component_types.get(str(item.get("component_id") or "")) == "temperature_source"
        }
        has_reference = any(item.type == "thermal_reference" for item in model.components)
        declared_temperature_sources = {
            item.id for item in model.components if item.type == "temperature_source"
        }
        if len(declared_temperature_sources) >= 2 and len(temperature_boundaries) < 2:
            report.add(
                "MISSING_TEMPERATURE_BOUNDARY",
                "Each two-boundary network must declare both temperature boundaries.",
                validator=type(self).__name__,
            )
        if not has_reference and len(temperature_boundaries) < 2:
            report.add(
                "MISSING_THERMAL_REFERENCE",
                "Thermal models require a thermal reference or two explicit temperature boundaries.",
                validator=type(self).__name__,
            )
        if not model.boundary_conditions:
            report.add("MISSING_BOUNDARY_CONDITION", "At least one explicit boundary condition is required.", validator=type(self).__name__)
        for index, boundary in enumerate(model.boundary_conditions):
            if str(boundary.get("component_id") or "") not in ids:
                report.add("UNKNOWN_BOUNDARY_COMPONENT", "Boundary condition references an unknown component.", path=f"boundary_conditions[{index}]", validator=type(self).__name__)


class OutputContractValidator:
    _logical_fields = frozenset({"id", "type", "source_component_id", "source_port"})
    _legacy_fields = frozenset({"component_id", "variable"})

    def __init__(self, output_registry: OutputRegistry) -> None:
        self.output_registry = output_registry

    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        raw_outputs = model.source_payload.get("requested_outputs")
        if not isinstance(raw_outputs, (list, tuple)):
            report.add(
                "OUTPUT_CONTRACT_INVALID",
                "Requested outputs must be a bounded list of logical objects.",
                path="requested_outputs",
                validator=type(self).__name__,
            )
            raw_outputs = ()
        for index, raw in enumerate(raw_outputs):
            if not isinstance(raw, dict):
                report.add(
                    "OUTPUT_CONTRACT_INVALID",
                    "Requested output must be a logical object.",
                    path=f"requested_outputs[{index}]",
                    validator=type(self).__name__,
                )
                continue
            allowed = self._legacy_fields if set(raw).issubset(self._legacy_fields) else self._logical_fields
            unknown_fields = sorted(set(raw) - allowed)
            if unknown_fields:
                report.add(
                    "OUTPUT_FIELD_NOT_ALLOWED",
                    "Requested output contains fields outside the logical contract.",
                    path=f"requested_outputs[{index}].{','.join(unknown_fields)}",
                    validator=type(self).__name__,
                )
        components = {item.id: item for item in model.components}
        seen_ids: set[str] = set()
        for index, requested in enumerate(model.requested_outputs):
            if not _SAFE_ID.fullmatch(requested.id):
                report.add(
                    "UNSAFE_OUTPUT_ID",
                    "Output ID must be a bounded logical identifier.",
                    path=f"requested_outputs[{index}].id",
                    validator=type(self).__name__,
                )
            if requested.id in seen_ids:
                report.add(
                    "DUPLICATE_OUTPUT_ID",
                    "Logical output IDs must be unique.",
                    path=f"requested_outputs[{index}].id",
                    validator=type(self).__name__,
                )
            seen_ids.add(requested.id)
            output_spec = self.output_registry.get(requested.type)
            if output_spec is None:
                report.add(
                    "UNKNOWN_OUTPUT_TYPE",
                    "Requested output type is not allowlisted.",
                    path=f"requested_outputs[{index}].type",
                    validator=type(self).__name__,
                )
            if requested.source_component_id not in components:
                report.add(
                    "UNKNOWN_OUTPUT_SOURCE",
                    "Requested output references an unknown component.",
                    path=f"requested_outputs[{index}].source_component_id",
                    validator=type(self).__name__,
                )
            elif (
                output_spec is not None
                and requested.source_component_id in components
                and components[requested.source_component_id].type not in output_spec.allowed_source_component_types
            ):
                report.add(
                    "INVALID_OUTPUT_TARGET",
                    "Requested output cannot instrument this component type.",
                    path=f"requested_outputs[{index}].source_component_id",
                    validator=type(self).__name__,
                )
            elif requested.source_port:
                source_component = components[requested.source_component_id]
                source_spec = registry.get(source_component.type)
                if source_spec is None or source_spec.port(requested.source_port) is None:
                    report.add(
                        "INVALID_OUTPUT_SOURCE_PORT",
                        "Requested output references an unknown source port.",
                        path=f"requested_outputs[{index}].source_port",
                        validator=type(self).__name__,
                    )


class ResourceLimitValidator:
    def __init__(self, limits: ValidationLimits) -> None:
        self.limits = limits

    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        if len(model.components) > self.limits.max_components:
            report.add("RESOURCE_LIMIT_COMPONENTS", "Model has too many components.", validator=type(self).__name__)
        if len(model.connections) > self.limits.max_connections:
            report.add("RESOURCE_LIMIT_CONNECTIONS", "Model has too many connections.", validator=type(self).__name__)
        if float(model.simulation_options.get("stop_time_s", 0) or 0) > self.limits.max_simulation_time_s:
            report.add("RESOURCE_LIMIT_SIMULATION_TIME", "Simulation time exceeds the configured limit.", validator=type(self).__name__)
        declared_signals = int(
            model.simulation_options.get("max_result_signals", len(model.requested_outputs)) or 0
        )
        if (
            declared_signals > self.limits.max_result_signals
            or len(model.requested_outputs) > self.limits.max_result_signals
            or len(model.requested_outputs) > declared_signals
        ):
            report.add("RESOURCE_LIMIT_RESULT_SIGNALS", "Requested signal count exceeds the configured limit.", validator=type(self).__name__)


class SimulationOptionValidator:
    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        convection_model = str(model.simulation_options.get("convection_model") or "linear").casefold()
        if convection_model != "linear":
            report.add(
                "UNSUPPORTED_CONVECTION_MODEL",
                "Only the reviewed constant-coefficient linear convection model is supported.",
                path="simulation_options.convection_model",
                validator=type(self).__name__,
            )


class SecurityValidator:
    _forbidden_keys = frozenset({
        "library_path", "block_path", "matlab_function", "function_name", "command", "script_path",
        "filesystem_path", "workspace_expression", "workspace_variable", "variable_name",
        "logger_variable", "logging_command", "compiler_mapping",
    })
    _forbidden_text = re.compile(r"(?:\.\.[\\/]|[A-Za-z]:[\\/]|\beval\s*\(|\bfeval\s*\(|\bsystem\s*\(|\.m\b|\.ssc\b)", re.IGNORECASE)

    def validate(self, model: ModelIR, registry: ComponentRegistry, report: ValidationReport) -> None:
        if not _SAFE_ID.fullmatch(model.model_id):
            report.add("UNSAFE_MODEL_ID", "Model ID must be a logical identifier.", path="model_id", validator=type(self).__name__)
        for index, component in enumerate(model.components):
            if not _SAFE_ID.fullmatch(component.id):
                report.add("UNSAFE_COMPONENT_ID", "Component ID must be a logical identifier.", path=f"components[{index}].id", validator=type(self).__name__)
        self._scan(model.source_payload, report, path="")

    def _scan(self, value: Any, report: ValidationReport, *, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                if str(key).casefold() in self._forbidden_keys:
                    report.add("UNSAFE_IR_FIELD", "Executable or path-bearing fields are forbidden in Model IR.", path=child, validator=type(self).__name__)
                self._scan(item, report, path=child)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                self._scan(item, report, path=f"{path}[{index}]")
        elif isinstance(value, str) and self._forbidden_text.search(value):
            report.add("UNSAFE_IR_VALUE", "Executable expressions and paths are forbidden in Model IR.", path=path, validator=type(self).__name__)


class ModelValidator:
    def __init__(
        self,
        registry: ComponentRegistry,
        *,
        limits: ValidationLimits | None = None,
        output_registry: OutputRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.limits = limits or ValidationLimits()
        self.output_registry = output_registry or OutputRegistry.default()
        self.layers: tuple[ValidatorLayer, ...] = (
            SchemaValidator(), SecurityValidator(), RegistryValidator(), ParameterValidator(), UnitValidator(),
            TopologyValidator(), ThermalGraphValidator(self.limits), BoundaryConditionValidator(), OutputContractValidator(self.output_registry),
            SimulationOptionValidator(), ResourceLimitValidator(self.limits),
        )

    def validate(self, model: ModelIR) -> ValidationReport:
        report = ValidationReport()
        for layer in self.layers:
            layer.validate(model, self.registry, report)
        return report

    def validate_for_compilation(self, model: ModelIR) -> ValidatedModelIR:
        report = self.validate(model)
        if not report.valid:
            raise ModelValidationError(report)
        return ValidatedModelIR(model, report, _seal=_VALIDATION_SEAL)


__all__ = [
    "BoundaryConditionValidator", "ModelValidator", "ParameterValidator", "RegistryValidator",
    "ResourceLimitValidator", "SchemaValidator", "SecurityValidator", "ThermalGraphValidator", "TopologyValidator",
    "SimulationOptionValidator", "UnitValidator", "ValidatedModelIR", "ValidationIssue", "ValidationLimits", "ValidationReport",
    "ModelValidationError",
]


def _bounded_branch_shape(graph: Any, junctions: list[str]) -> tuple[bool, int]:
    if len(junctions) != 2:
        return False, 0
    left, right = junctions
    if graph.degree.get(left) != graph.degree.get(right):
        return False, 0
    non_junction_nodes = set(graph.adjacency) - {left, right}
    parent = {node: node for node in non_junction_nodes}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(first: str, second: str) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    direct_paths = 0
    for edge in graph.elements:
        endpoints = {edge.left_node, edge.right_node}
        if endpoints == {left, right}:
            direct_paths += 1
        elif edge.left_node in non_junction_nodes and edge.right_node in non_junction_nodes:
            union(edge.left_node, edge.right_node)
    groups: dict[str, set[str]] = {}
    for node in non_junction_nodes:
        groups.setdefault(find(node), set()).add(node)
    boundary_nodes = set(graph.boundary_nodes.values())
    branch_paths = direct_paths
    side_attachments: list[tuple[str, str]] = []
    for nodes in groups.values():
        attachments: set[str] = set()
        for edge in graph.elements:
            if edge.left_node in nodes and edge.right_node in {left, right}:
                attachments.add(edge.right_node)
            if edge.right_node in nodes and edge.left_node in {left, right}:
                attachments.add(edge.left_node)
        boundaries = nodes & boundary_nodes
        if attachments == {left, right} and not boundaries:
            branch_paths += 1
        elif len(attachments) == 1 and len(boundaries) == 1:
            side_attachments.append((next(iter(attachments)), next(iter(boundaries))))
        elif any(graph.degree.get(node, 0) for node in nodes):
            return False, branch_paths
    side_junctions = {item[0] for item in side_attachments}
    side_boundaries = {item[1] for item in side_attachments}
    valid = (
        branch_paths >= 2
        and len(side_attachments) == 2
        and side_junctions == {left, right}
        and len(side_boundaries) == 2
    )
    return valid, branch_paths


def _measurement_reference_ids(model: ModelIR) -> set[str]:
    if len([item for item in model.components if item.type == "temperature_source"]) < 2:
        return set()
    if not any(item.type == "temperature" for item in model.requested_outputs):
        return set()
    return {item.id for item in model.components if item.type == "thermal_reference"}
