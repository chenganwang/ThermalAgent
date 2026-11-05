from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    name_zh: str
    name_en: str
    domain: str
    description: str
    supported_models: tuple[str, ...]
    default_model_id: str | None
    input_schema: tuple[dict[str, Any], ...]
    output_schema: tuple[dict[str, Any], ...]
    assumptions: tuple[str, ...]
    applicability: tuple[str, ...]
    limitations: tuple[str, ...]
    status: str
    provenance_status: str
    version: str = "1.0.0"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScenarioDefinition":
        return cls(
            scenario_id=str(payload["scenario_id"]), name_zh=str(payload["name_zh"]),
            name_en=str(payload["name_en"]), domain=str(payload["domain"]),
            description=str(payload.get("description") or ""),
            supported_models=tuple(str(x) for x in payload.get("supported_models") or ()),
            default_model_id=str(payload["default_model_id"]) if payload.get("default_model_id") else None,
            input_schema=tuple(dict(x) for x in payload.get("input_schema") or ()),
            output_schema=tuple(dict(x) for x in payload.get("output_schema") or ()),
            assumptions=tuple(str(x) for x in payload.get("assumptions") or ()),
            applicability=tuple(str(x) for x in payload.get("applicability") or ()),
            limitations=tuple(str(x) for x in payload.get("limitations") or ()),
            status=str(payload["status"]), provenance_status=str(payload["provenance_status"]),
            version=str(payload.get("version") or "1.0.0"),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for name in ("supported_models", "input_schema", "output_schema", "assumptions", "applicability", "limitations"):
            result[name] = list(result[name])
        return result


@dataclass(frozen=True)
class ModelDefinition:
    model_id: str
    scenario_id: str
    name_zh: str
    version: str
    solver: str
    adapter_id: str | None
    entrypoint_id: str | None
    execution_mode: str
    status: str
    human_validated: bool
    allowed_inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    source: dict[str, Any]
    file: dict[str, Any] | None
    hash: str | None
    registration_type: str
    asset_id: str | None = None
    sha256: str | None = None
    display_name: str = ""
    domain: str = "other"
    scenario_types: tuple[str, ...] = ()
    description: str = ""
    backend: str = ""
    matlab_entrypoint: str | None = None
    dispatcher_model_id: str | None = None
    experimental: bool = False
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    supports_execution: bool = False
    requires_model_file: bool = False
    cfd: bool = False
    selection_keywords: tuple[str, ...] = ()
    alternative_input_groups: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModelDefinition":
        model_id = str(payload["model_id"])
        scenario_id = str(payload["scenario_id"])
        solver = str(payload["solver"])
        execution_mode = str(payload["execution_mode"])
        status = str(payload["status"])
        allowed_inputs = tuple(str(x) for x in payload.get("allowed_inputs") or ())
        outputs = tuple(str(x) for x in payload.get("outputs") or ())
        groups = payload.get("alternative_input_groups", [])
        if not isinstance(groups, (list, tuple)):
            raise CatalogConfigurationError(f"invalid alternative_input_groups: {model_id}")
        group_ids: set[str] = set()
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("group_id"), str) or not group["group_id"].strip():
                raise CatalogConfigurationError(f"invalid alternative group: {model_id}")
            options = group.get("any_of")
            if group["group_id"] in group_ids or not isinstance(options, list) or not options:
                raise CatalogConfigurationError(f"invalid alternative group options: {model_id}")
            if any(not isinstance(option, list) or not option or any(not isinstance(name, str) or not name.strip() for name in option) for option in options):
                raise CatalogConfigurationError(f"invalid alternative group fields: {model_id}")
            group_ids.add(group["group_id"])
        return cls(
            model_id=model_id, scenario_id=scenario_id,
            name_zh=str(payload["name_zh"]), version=str(payload["version"]), solver=solver,
            adapter_id=str(payload["adapter_id"]) if payload.get("adapter_id") else None,
            entrypoint_id=str(payload["entrypoint_id"]) if payload.get("entrypoint_id") else None,
            execution_mode=execution_mode, status=status,
            human_validated=bool(payload.get("human_validated", False)),
            allowed_inputs=allowed_inputs,
            outputs=outputs,
            assumptions=tuple(str(x) for x in payload.get("assumptions") or ()),
            limitations=tuple(str(x) for x in payload.get("limitations") or ()),
            source=dict(payload.get("source") or {}), file=dict(payload["file"]) if payload.get("file") else None,
            hash=str(payload["hash"]) if payload.get("hash") else None,
            registration_type=str(payload["registration_type"]),
            asset_id=str(payload["asset_id"]) if payload.get("asset_id") else None,
            sha256=str(payload["sha256"]) if payload.get("sha256") else None,
            display_name=str(payload.get("display_name") or payload["name_zh"]),
            domain=str(payload.get("domain") or "other"),
            scenario_types=tuple(str(x) for x in payload.get("scenario_types") or (scenario_id,)),
            description=str(payload.get("description") or ""),
            backend=str(payload.get("backend") or solver),
            matlab_entrypoint=str(payload["matlab_entrypoint"]) if payload.get("matlab_entrypoint") else None,
            dispatcher_model_id=str(payload["dispatcher_model_id"]) if payload.get("dispatcher_model_id") else None,
            experimental=bool(payload.get("experimental", status == "experimental")),
            required_inputs=tuple(str(x) for x in payload.get("required_inputs", allowed_inputs)),
            optional_inputs=tuple(str(x) for x in payload.get("optional_inputs") or ()),
            expected_outputs=tuple(str(x) for x in payload.get("expected_outputs") or outputs),
            supports_execution=bool(
                payload.get("supports_execution", status == "available" and execution_mode != "preparation_only")
            ),
            requires_model_file=bool(payload.get("requires_model_file", False)),
            cfd=bool(payload.get("cfd", solver.lower() in {"openfoam", "comsol", "ansys_fluent"})),
            selection_keywords=tuple(str(x) for x in payload.get("selection_keywords") or ()),
            alternative_input_groups=tuple(dict(x) for x in groups),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for name in (
            "allowed_inputs",
            "outputs",
            "assumptions",
            "limitations",
            "scenario_types",
            "required_inputs",
            "optional_inputs",
            "expected_outputs",
            "selection_keywords",
            "alternative_input_groups",
        ):
            result[name] = list(result[name])
        return result

    def missing_inputs(self, inputs: Mapping[str, Any]) -> list[str]:
        def supplied(name: str) -> bool:
            value = inputs.get(name)
            return value is not None and not (isinstance(value, str) and not value.strip())

        missing = [name for name in self.required_inputs if not supplied(name)]
        for group in self.alternative_input_groups:
            if not any(all(supplied(name) for name in option) for option in group["any_of"]):
                missing.append(group["group_id"])
        return missing

    def to_public_dict(self) -> dict[str, Any]:
        """Return the stable catalog contract while retaining legacy fields."""

        return self.to_dict()


@dataclass(frozen=True)
class ExecutorDefinition:
    executor_id: str
    name_zh: str
    version: str
    solver: str
    adapter_id: str
    entrypoint_id: str
    status: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutorDefinition":
        return cls(**{name: str(payload[name]) for name in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    normalized_params: dict[str, Any] = field(default_factory=dict)
    missing_parameters: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CatalogConfigurationError(RuntimeError):
    pass


__all__ = ["CatalogConfigurationError", "ExecutorDefinition", "ModelDefinition", "ScenarioDefinition", "ValidationResult"]
