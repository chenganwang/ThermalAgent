from __future__ import annotations

from math import isfinite
from pathlib import Path
import re
from typing import Any, Protocol

from .compiler import CompilationError, CompilationPlan, output_logger_name
from .output_registry import OutputRegistry
from .registry import ComponentRegistry


_SAFE_MODEL_NAME = re.compile(r"^ta_[a-f0-9]{20}$")
_SAFE_OUTPUT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_ALLOWED_OPERATION_KINDS = frozenset({
    "create_model", "add_component", "set_parameter", "connect_ports", "instrument_output",
    "set_solver", "save_artifact",
})


class GeneratedModelRuntime(Protocol):
    def compile_generated_model(self, plan: CompilationPlan, target_path: Path) -> None: ...
    def verify_generated_model(self, plan: CompilationPlan, target_path: Path) -> None: ...


class SimulinkCompilerBackend:
    """Compiler adapter that delegates Engine ownership to MatlabRuntimeManager."""

    artifact_suffix = ".slx"
    backend_name = "matlab_simulink_simscape"

    def __init__(self, runtime: GeneratedModelRuntime) -> None:
        self._runtime = runtime

    def compile(self, plan: CompilationPlan, target_path: Path) -> None:
        if not isinstance(plan, CompilationPlan) or not plan.authentic:
            raise CompilationError("UNAUTHENTICATED_PLAN", "Compilation plan is not planner-issued.")
        self._runtime.compile_generated_model(plan, target_path)

    def verify(self, plan: CompilationPlan, target_path: Path) -> None:
        if not isinstance(plan, CompilationPlan) or not plan.authentic:
            raise CompilationError("UNAUTHENTICATED_PLAN", "Compilation plan is not planner-issued.")
        self._runtime.verify_generated_model(plan, target_path)


def execute_reviewed_compilation_plan(engine: object, plan: CompilationPlan, target_path: Path) -> None:
    """Execute only sealed operations rechecked against the built-in R2025a registry.

    This function has no Engine lifecycle responsibility and accepts no user
    command, function name, library path, workspace expression, or output path.
    The target is supplied only by the controlled artifact store/runtime seam.
    """

    registry = ComponentRegistry.default()
    operations = [item.to_dict() for item in plan.operations]
    output_registry = OutputRegistry.default()
    component_specs = _verify_plan(plan, operations, registry, output_registry)
    target = Path(target_path).resolve()
    if target.suffix.casefold() != ".slx":
        raise CompilationError("ARTIFACT_FORMAT_NOT_ALLOWED", "Real compiler target must be an SLX artifact.")

    model = plan.model_name
    loaded = False
    libraries: set[str] = set()
    try:
        engine.new_system(model, nargout=0)
        loaded = True
        for operation in operations:
            kind = operation["kind"]
            if kind == "create_model":
                continue
            if kind == "add_component":
                spec = component_specs[operation["component_id"]]
                library_id = str(spec.compiler_mapping["library_id"])
                if library_id not in libraries:
                    engine.load_system(library_id, nargout=0)
                    libraries.add(library_id)
                destination = f"{model}/{operation['component_id']}"
                engine.add_block(str(spec.compiler_mapping["block_path"]), destination, nargout=0)
                position = "[" + " ".join(str(int(value)) for value in operation["position"]) + "]"
                engine.set_param(destination, "Position", position, nargout=0)
            elif kind == "set_parameter":
                destination = f"{model}/{operation['component_id']}"
                engine.set_param(
                    destination,
                    operation["compiler_parameter"],
                    _numeric_literal(operation["value"]),
                    nargout=0,
                )
                if operation["compiler_unit_parameter"]:
                    engine.set_param(
                        destination,
                        operation["compiler_unit_parameter"],
                        operation["unit"],
                        nargout=0,
                    )
            elif kind == "connect_ports":
                left = _physical_port_handle(engine, model, operation["from_component"], operation["from_port"])
                right = _physical_port_handle(engine, model, operation["to_component"], operation["to_port"])
                engine.add_line(model, left, right, "autorouting", "on", nargout=1)
            elif kind == "instrument_output":
                output_spec = output_registry.require(operation["output_type"])
                for library_id in (
                    output_spec.sensor_library_id,
                    output_spec.converter_library_id,
                    output_spec.logger_library_id,
                ):
                    if library_id not in libraries:
                        engine.load_system(library_id, nargout=0)
                        libraries.add(library_id)
                destinations = {
                    "sensor": f"{model}/{operation['sensor_id']}",
                    "converter": f"{model}/{operation['converter_id']}",
                    "logger": f"{model}/{operation['logger_id']}",
                }
                for role, block_path, position_key in (
                    ("sensor", output_spec.sensor_block_path, "sensor_position"),
                    ("converter", output_spec.converter_block_path, "converter_position"),
                    ("logger", output_spec.logger_block_path, "logger_position"),
                ):
                    engine.add_block(block_path, destinations[role], nargout=0)
                    position = "[" + " ".join(str(int(value)) for value in operation[position_key]) + "]"
                    engine.set_param(destinations[role], "Position", position, nargout=0)
                engine.set_param(destinations["converter"], "Unit", output_spec.canonical_unit, nargout=0)
                engine.set_param(
                    destinations["logger"],
                    "VariableName", operation["logger_name"],
                    "SaveFormat", "Structure With Time",
                    "MaxDataPoints", str(operation["max_samples"]),
                    "Decimation", "1",
                    "SampleTime", "-1",
                    nargout=0,
                )
                source = _block_port_handle(
                    engine, f"{model}/{operation['source_component_id']}", operation["source_port"],
                )
                peer = _block_port_handle(
                    engine, f"{model}/{operation['peer_component_id']}", operation["peer_port"],
                )
                sensor_a = _block_port_handle(engine, destinations["sensor"], output_spec.sensor_a_port.to_dict())
                sensor_b = _block_port_handle(engine, destinations["sensor"], output_spec.sensor_b_port.to_dict())
                sensor_signal = _block_port_handle(
                    engine, destinations["sensor"], output_spec.sensor_signal_port.to_dict(),
                )
                converter_input = _block_port_handle(
                    engine, destinations["converter"], output_spec.converter_input_port.to_dict(),
                )
                converter_output = _block_port_handle(
                    engine, destinations["converter"], output_spec.converter_output_port.to_dict(),
                )
                logger_input = _block_port_handle(
                    engine, destinations["logger"], output_spec.logger_input_port.to_dict(),
                )
                for left, right in (
                    (source, sensor_a),
                    (sensor_b, peer),
                    (sensor_signal, converter_input),
                    (converter_output, logger_input),
                ):
                    engine.add_line(model, left, right, "autorouting", "on", nargout=1)
            elif kind == "set_solver":
                engine.set_param(
                    model, "Solver", operation["solver"], "SolverType", operation["solver_type"], nargout=0,
                )
            elif kind == "save_artifact":
                engine.save_system(model, str(target), nargout=0)
                engine.close_system(model, 0, nargout=0)
                loaded = False
                engine.load_system(str(target), nargout=0)
                loaded = True
        if not target.is_file() or target.stat().st_size <= 0:
            raise CompilationError("ARTIFACT_NOT_CREATED", "MATLAB did not create a non-empty SLX artifact.")
    finally:
        if loaded:
            try:
                engine.close_system(model, 0, nargout=0)
            except Exception:
                pass


def _verify_plan(
    plan: CompilationPlan,
    operations: list[dict[str, Any]],
    registry: ComponentRegistry,
    output_registry: OutputRegistry,
) -> dict[str, Any]:
    if not isinstance(plan, CompilationPlan) or not plan.authentic:
        raise CompilationError("UNAUTHENTICATED_PLAN", "Compilation plan is not planner-issued.")
    if not _SAFE_MODEL_NAME.fullmatch(plan.model_name) or plan.model_name != f"ta_{plan.model_ir_hash[:20]}":
        raise CompilationError("MODEL_NAME_INVALID", "Compilation model name is not hash-derived.")
    if not operations or operations[0] != {"kind": "create_model", "model_name": plan.model_name}:
        raise CompilationError("COMPILATION_PLAN_INVALID", "Plan must begin with its fixed create-model operation.")
    if any(item.get("kind") not in _ALLOWED_OPERATION_KINDS for item in operations):
        raise CompilationError("COMPILATION_OPERATION_NOT_ALLOWED", "Compilation plan contains an unknown operation.")
    if sum(item["kind"] == "save_artifact" for item in operations) != 1:
        raise CompilationError("COMPILATION_PLAN_INVALID", "Plan must contain one controlled save operation.")
    if plan.output_registry_version != output_registry.registry_version:
        raise CompilationError("OUTPUT_REGISTRY_MISMATCH", "Plan output registry version is not reviewed.")

    components: dict[str, Any] = {}
    for item in operations:
        if item["kind"] != "add_component":
            continue
        component_id = str(item.get("component_id") or "")
        spec = registry.require(str(item.get("component_type") or ""))
        if not spec.compiler_available or item.get("reviewed_block_path") != spec.compiler_mapping.get("block_path"):
            raise CompilationError("BLOCK_MAPPING_MISMATCH", "Plan block mapping differs from the reviewed registry.")
        if component_id in components:
            raise CompilationError("COMPILATION_PLAN_INVALID", "Plan contains a duplicate component ID.")
        components[component_id] = spec

    instrument_ordinal = 0
    output_ids: set[str] = set()
    for item in operations:
        kind = item["kind"]
        if kind == "set_parameter":
            spec = components.get(item.get("component_id"))
            parameter = spec.parameter(str(item.get("logical_parameter") or "")) if spec else None
            if (
                spec is not None
                and spec.compiler_mapping.get("lowering") == "layer_to_resistance"
                and item.get("logical_parameter") == "equivalent_resistance_k_w"
            ):
                if (
                    item.get("compiler_parameter") != "resistance"
                    or item.get("compiler_unit_parameter") != "resistance_unit"
                    or item.get("unit") != "K/W"
                    or float(item.get("value") or 0.0) <= 0.0
                ):
                    raise CompilationError(
                        "PARAMETER_MAPPING_MISMATCH",
                        "Conductive-layer lowering differs from the reviewed resistance mapping.",
                    )
                _numeric_literal(item.get("value"))
                continue
            if parameter is None:
                raise CompilationError("PARAMETER_MAPPING_NOT_AVAILABLE", "Parameter is absent from the reviewed registry.")
            expected_unit = parameter.compiler_unit or parameter.canonical_unit
            if (
                item.get("compiler_parameter") != parameter.compiler_parameter
                or item.get("compiler_unit_parameter") != parameter.compiler_unit_parameter
                or item.get("unit") != expected_unit
            ):
                raise CompilationError("PARAMETER_MAPPING_MISMATCH", "Parameter mapping differs from the reviewed registry.")
            _numeric_literal(item.get("value"))
        elif kind == "connect_ports":
            for prefix in ("from", "to"):
                spec = components.get(item.get(f"{prefix}_component"))
                locator = item.get(f"{prefix}_port") or {}
                port = spec.port(str(locator.get("logical_name") or "")) if spec else None
                if port is None or locator != {
                    "logical_name": port.name,
                    "handle_family": port.compiler_handle_family,
                    "handle_index": port.compiler_handle_index,
                }:
                    raise CompilationError("PORT_MAPPING_MISMATCH", "Port mapping differs from the reviewed registry.")
        elif kind == "instrument_output":
            instrument_ordinal += 1
            output_id = str(item.get("output_id") or "")
            output_type = str(item.get("output_type") or "")
            output_spec = output_registry.get(output_type)
            source = components.get(item.get("source_component_id"))
            peer = components.get(item.get("peer_component_id"))
            if not _SAFE_OUTPUT_ID.fullmatch(output_id) or output_id in output_ids:
                raise CompilationError("OUTPUT_ID_INVALID", "Instrumentation output ID is invalid or duplicated.")
            output_ids.add(output_id)
            if output_spec is None or source is None or peer is None:
                raise CompilationError("OUTPUT_MAPPING_MISMATCH", "Instrumentation mapping is not reviewed.")
            source_type = str(item.get("source_component_type") or "")
            source_locator = item.get("source_port") or {}
            source_port_name = str(source_locator.get("logical_name") or "")
            source_port = source.port(source_port_name) if source_type == source.component_type else None
            if source_type not in output_spec.allowed_source_component_types or source_port is None:
                raise CompilationError("OUTPUT_TARGET_MISMATCH", "Instrumentation target is not reviewed.")
            peer_locator = item.get("peer_port") or {}
            peer_port = peer.port(str(peer_locator.get("logical_name") or ""))
            if source_locator != _locator_dict(source_port) or peer_port is None or peer_locator != _locator_dict(peer_port):
                raise CompilationError("OUTPUT_PORT_MAPPING_MISMATCH", "Instrumentation port differs from the reviewed registry.")
            expected_ids = {
                "sensor_id": f"instrument_{instrument_ordinal}_sensor",
                "converter_id": f"instrument_{instrument_ordinal}_converter",
                "logger_id": f"instrument_{instrument_ordinal}_logger",
            }
            if any(item.get(key) != value for key, value in expected_ids.items()):
                raise CompilationError("OUTPUT_BLOCK_ID_MISMATCH", "Instrumentation block IDs are not deterministic.")
            if (
                item.get("quantity") != output_spec.quantity
                or item.get("unit") != output_spec.canonical_unit
                or item.get("max_samples") != output_spec.max_samples
                or item.get("logger_name") != output_logger_name(plan.model_ir_hash, output_id, output_type)
            ):
                raise CompilationError("OUTPUT_CONTRACT_MISMATCH", "Instrumentation contract differs from the registry.")
        elif kind == "set_solver" and item != {"kind": "set_solver", "solver": "ode23t", "solver_type": "Variable-step"}:
            raise CompilationError("SOLVER_MAPPING_MISMATCH", "Solver settings are not allowlisted.")
        elif kind == "save_artifact" and item != {"kind": "save_artifact", "artifact_format": "slx"}:
            raise CompilationError("ARTIFACT_FORMAT_NOT_ALLOWED", "Save operation is not allowlisted.")
    return components


def _numeric_literal(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise CompilationError("PARAMETER_NOT_FINITE", "Compiler parameter must be a finite number.")
    return format(float(value), ".17g")


def _physical_port_handle(
    engine: object,
    model: str,
    component_id: str,
    locator: dict[str, Any],
) -> float:
    return _block_port_handle(engine, f"{model}/{component_id}", locator)


def _block_port_handle(engine: object, block: str, locator: dict[str, Any]) -> float:
    handles = engine.get_param(block, "PortHandles", nargout=1)
    family = str(locator["handle_family"])
    index = int(locator["handle_index"])
    raw = handles.get(family) if isinstance(handles, dict) else getattr(handles, family, None)
    values = _flatten_numeric(raw)
    if index < 0 or index >= len(values):
        raise CompilationError("PORT_HANDLE_NOT_AVAILABLE", "Reviewed physical port handle is unavailable.")
    return values[index]


def _locator_dict(port: Any) -> dict[str, Any]:
    return {
        "logical_name": port.name,
        "handle_family": port.compiler_handle_family,
        "handle_index": port.compiler_handle_index,
    }


def _flatten_numeric(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    result: list[float] = []
    try:
        for item in value:
            result.extend(_flatten_numeric(item))
    except TypeError:
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            pass
    return result


__all__ = ["SimulinkCompilerBackend", "execute_reviewed_compilation_plan"]
