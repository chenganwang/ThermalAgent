from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Protocol
from uuid import uuid4

from .model_ir import ModelIR, RequestedOutput
from .output_registry import OutputRegistry, OutputSpec
from .registry import ComponentRegistry, ComponentSpec, ParameterSpec, PortSpec
from .validator import ValidatedModelIR


_PLAN_SEAL = object()
_SAFE_ARTIFACT_ID = re.compile(r"^gm_[a-f0-9]{16}_[a-f0-9]{12}$")
_ALLOWED_SUFFIXES = frozenset({".slx", ".fake.json"})


class CompilationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PortLocator:
    logical_name: str
    handle_family: str
    handle_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "handle_family": self.handle_family,
            "handle_index": self.handle_index,
        }


@dataclass(frozen=True)
class CompilationOperation:
    kind: str
    fields: tuple[tuple[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind}
        for key, value in self.fields:
            result[key] = value.to_dict() if isinstance(value, PortLocator) else value
        return result


class CompilationPlan:
    """Sealed deterministic plan produced only from a ValidatedModelIR."""

    __slots__ = (
        "model_name", "model_ir_hash", "registry_version", "output_registry_version", "compiler_version",
        "matlab_release", "operations", "_seal",
    )

    def __init__(
        self,
        *,
        model_name: str,
        model_ir_hash: str,
        registry_version: str,
        output_registry_version: str,
        compiler_version: str,
        matlab_release: str,
        operations: tuple[CompilationOperation, ...],
        _seal: object,
    ) -> None:
        if _seal is not _PLAN_SEAL:
            raise TypeError("CompilationPlan can only be issued by CompilationPlanner")
        self.model_name = model_name
        self.model_ir_hash = model_ir_hash
        self.registry_version = registry_version
        self.output_registry_version = output_registry_version
        self.compiler_version = compiler_version
        self.matlab_release = matlab_release
        self.operations = operations
        self._seal = _seal

    @property
    def authentic(self) -> bool:
        return self._seal is _PLAN_SEAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_ir_hash": self.model_ir_hash,
            "registry_version": self.registry_version,
            "output_registry_version": self.output_registry_version,
            "compiler_version": self.compiler_version,
            "matlab_release": self.matlab_release,
            "operations": [item.to_dict() for item in self.operations],
        }


class CompilationPlanner:
    compiler_version = "thermalagent-simscape-compiler-v2"

    def __init__(
        self,
        registry: ComponentRegistry,
        capabilities: dict[str, Any],
        *,
        output_registry: OutputRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.output_registry = output_registry or OutputRegistry.default()
        self.capabilities = dict(capabilities or {})

    def build(self, validated: ValidatedModelIR) -> CompilationPlan:
        if not isinstance(validated, ValidatedModelIR) or not validated.authentic:
            raise CompilationError("UNVALIDATED_MODEL_IR", "Compiler input must be a validator-issued Model IR.")
        model = validated.model_ir
        self._require_base_capabilities(model.model_domain)
        operations: list[CompilationOperation] = [
            _operation("create_model", model_name=f"ta_{validated.model_ir_hash[:20]}")
        ]
        specs: dict[str, ComponentSpec] = {}
        for index, component in enumerate(model.components):
            spec = self.registry.get(component.type)
            if spec is None or not spec.compiler_available:
                raise CompilationError("COMPONENT_NOT_COMPILER_AVAILABLE", "Component has no reviewed compiler mapping.")
            self._require_component_capabilities(spec)
            specs[component.id] = spec
            operations.append(_operation(
                "add_component",
                component_id=component.id,
                component_type=component.type,
                reviewed_block_path=str(spec.compiler_mapping["block_path"]),
                position=_position(index),
            ))
            normalized = validated.report.normalized_parameters.get(component.id, {})
            if spec.compiler_mapping.get("lowering") == "layer_to_resistance":
                try:
                    resistance = (
                        float(normalized["thickness_m"])
                        / (float(normalized["conductivity_w_mk"]) * float(normalized["area_m2"]))
                    )
                except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                    raise CompilationError(
                        "PARAMETER_MAPPING_NOT_AVAILABLE", "Conductive-layer parameters cannot be lowered.",
                    ) from exc
                operations.append(_operation(
                    "set_parameter",
                    component_id=component.id,
                    logical_parameter="equivalent_resistance_k_w",
                    compiler_parameter="resistance",
                    compiler_unit_parameter="resistance_unit",
                    value=resistance,
                    unit="K/W",
                ))
                continue
            for parameter in spec.parameters:
                if parameter.name not in component.parameters and parameter.default is None:
                    continue
                if not parameter.compiler_parameter:
                    raise CompilationError("PARAMETER_MAPPING_NOT_AVAILABLE", "Parameter has no reviewed compiler mapping.")
                value = normalized.get(parameter.name, parameter.default)
                if value is None:
                    continue
                operations.append(_parameter_operation(component.id, parameter, value))

        replaced_connections: set[int] = set()
        instrumentation: list[CompilationOperation] = []
        for index, requested in enumerate(model.requested_outputs):
            operation, replaced_index = self._instrumentation_operation(
                model,
                specs,
                requested,
                output_index=index,
                model_ir_hash=validated.model_ir_hash,
            )
            instrumentation.append(operation)
            if replaced_index is not None:
                if replaced_index in replaced_connections:
                    raise CompilationError(
                        "OUTPUT_TARGET_ALREADY_INSTRUMENTED",
                        "Only one series output may instrument a physical connection.",
                    )
                replaced_connections.add(replaced_index)

        for connection_index, connection in enumerate(model.connections):
            if connection_index in replaced_connections:
                continue
            left = specs.get(connection.from_component)
            right = specs.get(connection.to_component)
            left_port = left.port(connection.from_port) if left else None
            right_port = right.port(connection.to_port) if right else None
            if left_port is None or right_port is None:
                raise CompilationError("PORT_MAPPING_NOT_AVAILABLE", "Connection has no reviewed port mapping.")
            operations.append(_operation(
                "connect_ports",
                from_component=connection.from_component,
                from_port=_port_locator(left_port),
                to_component=connection.to_component,
                to_port=_port_locator(right_port),
            ))

        operations.extend(instrumentation)
        operations.extend((
            _operation("set_solver", solver="ode23t", solver_type="Variable-step"),
            _operation("save_artifact", artifact_format="slx"),
        ))
        return CompilationPlan(
            model_name=f"ta_{validated.model_ir_hash[:20]}",
            model_ir_hash=validated.model_ir_hash,
            registry_version=self.registry.registry_version,
            output_registry_version=self.output_registry.registry_version,
            compiler_version=self.compiler_version,
            matlab_release=_matlab_release(self.capabilities),
            operations=tuple(operations),
            _seal=_PLAN_SEAL,
        )

    def _instrumentation_operation(
        self,
        model: ModelIR,
        specs: dict[str, ComponentSpec],
        requested: RequestedOutput,
        *,
        output_index: int,
        model_ir_hash: str,
    ) -> tuple[CompilationOperation, int | None]:
        output_spec = self.output_registry.get(requested.type)
        source_component = next(
            (item for item in model.components if item.id == requested.source_component_id),
            None,
        )
        if output_spec is None or source_component is None:
            raise CompilationError("OUTPUT_MAPPING_NOT_AVAILABLE", "Requested output has no reviewed mapping.")
        self._require_output_capabilities(output_spec)
        source_spec = specs.get(source_component.id)
        source_port_name = (
            requested.source_port
            or output_spec.source_port_by_component_type.get(source_component.type)
        )
        source_port = source_spec.port(source_port_name) if source_spec and source_port_name else None
        if source_port is None:
            raise CompilationError("OUTPUT_PORT_MAPPING_NOT_AVAILABLE", "Output source port has no reviewed mapping.")

        peer_component_id: str
        peer_port_name: str
        replaced_index: int | None = None
        if output_spec.instrumentation_mode == "series_after_source":
            matches: list[tuple[int, str, str]] = []
            for index, connection in enumerate(model.connections):
                if connection.from_component == source_component.id and connection.from_port == source_port.name:
                    matches.append((index, connection.to_component, connection.to_port))
                elif connection.to_component == source_component.id and connection.to_port == source_port.name:
                    matches.append((index, connection.from_component, connection.from_port))
            if len(matches) != 1:
                raise CompilationError(
                    "OUTPUT_CONNECTION_NOT_INSTRUMENTABLE",
                    "Series output requires exactly one reviewed physical connection.",
                )
            replaced_index, peer_component_id, peer_port_name = matches[0]
        elif output_spec.instrumentation_mode == "temperature_to_reference":
            reference = next((item for item in model.components if item.type == "thermal_reference"), None)
            if reference is None:
                raise CompilationError("OUTPUT_REFERENCE_NOT_AVAILABLE", "Temperature output requires a reference.")
            peer_component_id, peer_port_name = reference.id, "H"
        else:
            raise CompilationError("OUTPUT_INSTRUMENTATION_NOT_AVAILABLE", "Output instrumentation is unavailable.")

        peer_spec = specs.get(peer_component_id)
        peer_port = peer_spec.port(peer_port_name) if peer_spec else None
        if peer_port is None:
            raise CompilationError("OUTPUT_PORT_MAPPING_NOT_AVAILABLE", "Output peer port has no reviewed mapping.")
        base_position = len(model.components) + output_index * 3
        ordinal = output_index + 1
        return _operation(
            "instrument_output",
            output_id=requested.id,
            output_type=requested.type,
            quantity=output_spec.quantity,
            unit=output_spec.canonical_unit,
            source_component_id=source_component.id,
            source_component_type=source_component.type,
            source_port=_port_locator(source_port),
            peer_component_id=peer_component_id,
            peer_port=_port_locator(peer_port),
            sensor_id=f"instrument_{ordinal}_sensor",
            sensor_position=_position(base_position),
            converter_id=f"instrument_{ordinal}_converter",
            converter_position=_position(base_position + 1),
            logger_id=f"instrument_{ordinal}_logger",
            logger_position=_position(base_position + 2),
            logger_name=output_logger_name(model_ir_hash, requested.id, requested.type),
            max_samples=output_spec.max_samples,
        ), replaced_index

    def _require_output_capabilities(self, spec: OutputSpec) -> None:
        for key, reviewed_path in (
            (spec.sensor_block_key, spec.sensor_block_path),
            (spec.converter_block_key, spec.converter_block_path),
            (spec.logger_block_key, spec.logger_block_path),
        ):
            approved = (self.capabilities.get("approved_blocks") or {}).get(key) or {}
            if not bool(approved.get("available")):
                raise CompilationError(
                    "CAPABILITY_NOT_AVAILABLE",
                    "Reviewed output instrumentation capability is unavailable.",
                )
            resolved = str(approved.get("resolved_path") or "")
            if resolved and resolved != reviewed_path:
                raise CompilationError(
                    "BLOCK_MAPPING_MISMATCH",
                    "Capability probe did not resolve the reviewed instrumentation block path.",
                )

    def _require_base_capabilities(self, domain: str) -> None:
        for key in ("simulink", "simscape"):
            if not bool((self.capabilities.get(key) or {}).get("available")):
                raise CompilationError("CAPABILITY_NOT_AVAILABLE", f"Required capability is unavailable: {key}")
        if not bool(((self.capabilities.get("domains") or {}).get(domain) or {}).get("available")):
            raise CompilationError("CAPABILITY_NOT_AVAILABLE", f"Physical domain is unavailable: {domain}")
        release = _matlab_release(self.capabilities)
        if release != "R2025a":
            raise CompilationError("MATLAB_VERSION_NOT_SUPPORTED", "Reviewed compiler mappings require R2025a.")

    def _require_component_capabilities(self, spec: ComponentSpec) -> None:
        approved = (self.capabilities.get("approved_blocks") or {}).get(spec.compiler_mapping.get("block_key")) or {}
        if not bool(approved.get("available")):
            raise CompilationError("CAPABILITY_NOT_AVAILABLE", "Reviewed MATLAB block is unavailable.")
        resolved = str(approved.get("resolved_path") or "")
        reviewed = str(spec.compiler_mapping.get("block_path") or "")
        if resolved and resolved != reviewed:
            raise CompilationError("BLOCK_MAPPING_MISMATCH", "Capability probe did not resolve the reviewed block path.")


class CompilerBackend(Protocol):
    artifact_suffix: str
    backend_name: str

    def compile(self, plan: CompilationPlan, target_path: Path) -> None: ...


class FakeCompilerBackend:
    """Deterministic resource-free backend for unit and contract tests only."""

    artifact_suffix = ".fake.json"
    backend_name = "fake_compiler"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.received_plans: list[CompilationPlan] = []

    def compile(self, plan: CompilationPlan, target_path: Path) -> None:
        if not plan.authentic:
            raise CompilationError("UNAUTHENTICATED_PLAN", "Compilation plan is not planner-issued.")
        self.received_plans.append(plan)
        if self.fail:
            raise RuntimeError("fake compiler failure")
        target_path.write_text(
            json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


@dataclass(frozen=True)
class ArtifactTarget:
    artifact_id: str
    temporary_path: Path
    final_path: Path


class GeneratedModelArtifactStore:
    """Internal staging paths; public contracts expose only opaque artifact IDs."""

    def __init__(self, root: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self.root = (Path(root) if root is not None else project_root / "runtime" / "generated_models").resolve()
        self.staging_root = (self.root / "staging").resolve()
        if not self.staging_root.is_relative_to(self.root):
            raise ValueError("generated-model staging escaped its controlled root")

    def allocate(self, model_ir_hash: str, suffix: str) -> ArtifactTarget:
        if suffix not in _ALLOWED_SUFFIXES:
            raise CompilationError("ARTIFACT_FORMAT_NOT_ALLOWED", "Compiler artifact format is not allowlisted.")
        artifact_id = f"gm_{model_ir_hash[:16]}_{uuid4().hex[:12]}"
        if not _SAFE_ARTIFACT_ID.fullmatch(artifact_id):
            raise CompilationError("ARTIFACT_ID_INVALID", "Generated artifact ID is invalid.")
        self.staging_root.mkdir(parents=True, exist_ok=True)
        final_path = (self.staging_root / f"{artifact_id}{suffix}").resolve()
        temporary_path = (self.staging_root / f"{artifact_id}_part{suffix}").resolve()
        if not final_path.is_relative_to(self.staging_root) or not temporary_path.is_relative_to(self.staging_root):
            raise CompilationError("ARTIFACT_PATH_ESCAPE", "Generated artifact path escaped staging.")
        return ArtifactTarget(artifact_id, temporary_path, final_path)

    def finalize(self, target: ArtifactTarget) -> None:
        if not target.temporary_path.is_file() or target.temporary_path.stat().st_size <= 0:
            raise CompilationError("ARTIFACT_NOT_CREATED", "Compiler did not create a non-empty artifact.")
        target.temporary_path.replace(target.final_path)

    def discard(self, target: ArtifactTarget) -> None:
        for path in (target.temporary_path, target.final_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def internal_path(self, artifact_id: str) -> Path:
        if not _SAFE_ARTIFACT_ID.fullmatch(str(artifact_id or "")):
            raise KeyError(artifact_id)
        matches = list(self.staging_root.glob(f"{artifact_id}.*")) if self.staging_root.exists() else []
        if len(matches) != 1:
            raise KeyError(artifact_id)
        resolved = matches[0].resolve()
        if not resolved.is_relative_to(self.staging_root):
            raise KeyError(artifact_id)
        return resolved

    def delete(self, artifact_id: str) -> bool:
        """Delete one artifact resolved exclusively through its opaque allowlisted ID."""
        try:
            path = self.internal_path(artifact_id)
        except KeyError:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CompilationError("ARTIFACT_DELETE_FAILED", "Generated artifact could not be removed.") from exc
        return True


@dataclass(frozen=True)
class CompilationResult:
    status: str
    artifact_id: str | None
    model_ir_hash: str
    compiler_version: str
    registry_version: str
    matlab_version: str
    backend: str
    created_at: str
    validation_report: dict[str, Any]
    errors: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "artifact_id": self.artifact_id,
            "model_ir_hash": self.model_ir_hash,
            "compiler_version": self.compiler_version,
            "registry_version": self.registry_version,
            "matlab_version": self.matlab_version,
            "backend": self.backend,
            "created_at": self.created_at,
            "validation_report": self.validation_report,
            "errors": list(self.errors),
        }


class ModelCompiler:
    def __init__(self, planner: CompilationPlanner, backend: CompilerBackend, store: GeneratedModelArtifactStore) -> None:
        self.planner = planner
        self.backend = backend
        self.store = store

    def compile(self, validated: ValidatedModelIR) -> CompilationResult:
        plan = self.planner.build(validated)
        target = self.store.allocate(plan.model_ir_hash, self.backend.artifact_suffix)
        try:
            self.backend.compile(plan, target.temporary_path)
            self.store.finalize(target)
            verifier = getattr(self.backend, "verify", None)
            if callable(verifier):
                verifier(plan, target.final_path)
        except Exception as exc:
            self.store.discard(target)
            code = exc.code if isinstance(exc, CompilationError) else "MODEL_COMPILATION_FAILED"
            return _result(plan, validated, self.backend.backend_name, status="failed", error=(code, type(exc).__name__))
        return _result(plan, validated, self.backend.backend_name, status="compiled", artifact_id=target.artifact_id)


def _operation(kind: str, **fields: Any) -> CompilationOperation:
    return CompilationOperation(kind, tuple(fields.items()))


def _parameter_operation(component_id: str, spec: ParameterSpec, value: float | int) -> CompilationOperation:
    return _operation(
        "set_parameter",
        component_id=component_id,
        logical_parameter=spec.name,
        compiler_parameter=spec.compiler_parameter,
        compiler_unit_parameter=spec.compiler_unit_parameter,
        value=float(value),
        unit=spec.compiler_unit or spec.canonical_unit,
    )


def _port_locator(port: PortSpec) -> PortLocator:
    if not port.compiler_handle_family or port.compiler_handle_index < 0:
        raise CompilationError("PORT_MAPPING_NOT_AVAILABLE", "Port has no reviewed compiler locator.")
    return PortLocator(port.name, port.compiler_handle_family, port.compiler_handle_index)


def _position(index: int) -> tuple[int, int, int, int]:
    column = index % 4
    row = index // 4
    left = 80 + column * 180
    top = 80 + row * 130
    return (left, top, left + 90, top + 60)


def _matlab_release(capabilities: dict[str, Any]) -> str:
    version = str((capabilities.get("matlab") or {}).get("version") or "")
    match = re.search(r"R\d{4}[ab]", version)
    return match.group(0) if match else ""


def output_logger_name(model_ir_hash: str, output_id: str, output_type: str) -> str:
    digest = hashlib.sha256(
        f"{model_ir_hash}:{output_id}:{output_type}".encode("utf-8")
    ).hexdigest()[:24]
    return f"tao_{digest}"


def _result(
    plan: CompilationPlan,
    validated: ValidatedModelIR,
    backend: str,
    *,
    status: str,
    artifact_id: str | None = None,
    error: tuple[str, str] | None = None,
) -> CompilationResult:
    return CompilationResult(
        status=status,
        artifact_id=artifact_id,
        model_ir_hash=plan.model_ir_hash,
        compiler_version=plan.compiler_version,
        registry_version=plan.registry_version,
        matlab_version=plan.matlab_release,
        backend=backend,
        created_at=datetime.now(timezone.utc).isoformat(),
        validation_report=validated.report.to_dict(),
        errors=({"code": error[0], "message": error[1]},) if error else (),
    )


__all__ = [
    "CompilationError", "CompilationOperation", "CompilationPlan", "CompilationPlanner",
    "CompilationResult", "CompilerBackend", "FakeCompilerBackend", "GeneratedModelArtifactStore",
    "ModelCompiler", "PortLocator", "output_logger_name",
]
