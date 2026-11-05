from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class ParameterValue:
    value: float | int | bool | str
    unit: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ParameterValue":
        return cls(value=payload.get("value"), unit=str(payload.get("unit") or ""))


@dataclass(frozen=True)
class IRComponent:
    id: str
    type: str
    parameters: dict[str, ParameterValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IRComponent":
        raw = payload.get("parameters") if isinstance(payload.get("parameters"), Mapping) else {}
        return cls(
            id=str(payload.get("id") or ""),
            type=str(payload.get("type") or ""),
            parameters={str(name): ParameterValue.from_dict(value) for name, value in raw.items() if isinstance(value, Mapping)},
        )


@dataclass(frozen=True)
class IRConnection:
    from_component: str
    from_port: str
    to_component: str
    to_port: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IRConnection":
        return cls(**{name: str(payload.get(name) or "") for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class RequestedOutput:
    """Logical, non-executable output request carried by Model IR."""

    id: str
    type: str
    source_component_id: str
    source_port: str = ""
    _legacy_variable: str = field(default="", repr=False, compare=False)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RequestedOutput":
        source_component_id = str(
            payload.get("source_component_id")
            or payload.get("source_component")
            or payload.get("component_id")
            or ""
        )
        legacy_variable = str(payload.get("variable") or "")
        output_type = str(payload.get("type") or {
            "temperature_k": "temperature",
            "heat_flow_w": "heat_flow",
        }.get(legacy_variable, ""))
        logical_id = str(payload.get("id") or "")
        if not logical_id and source_component_id and output_type:
            logical_id = f"{source_component_id}_{output_type}"
        return cls(
            logical_id, output_type, source_component_id,
            str(payload.get("source_port") or ""), legacy_variable,
        )

    def to_dict(self) -> dict[str, str]:
        if self._legacy_variable:
            return {"component_id": self.source_component_id, "variable": self._legacy_variable}
        result = {"id": self.id, "type": self.type, "source_component_id": self.source_component_id}
        if self.source_port:
            result["source_port"] = self.source_port
        return result


@dataclass(frozen=True)
class ModelIR:
    schema_version: str
    model_id: str
    model_domain: str
    components: tuple[IRComponent, ...]
    connections: tuple[IRConnection, ...]
    parameters: dict[str, Any]
    boundary_conditions: tuple[dict[str, Any], ...]
    requested_outputs: tuple[RequestedOutput, ...]
    simulation_options: dict[str, Any]
    source_payload: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModelIR":
        raw = dict(payload or {})
        return cls(
            schema_version=str(raw.get("schema_version") or ""),
            model_id=str(raw.get("model_id") or ""),
            model_domain=str(raw.get("model_domain") or ""),
            components=tuple(IRComponent.from_dict(item) for item in raw.get("components") or () if isinstance(item, Mapping)),
            connections=tuple(IRConnection.from_dict(item) for item in raw.get("connections") or () if isinstance(item, Mapping)),
            parameters=dict(raw.get("parameters") or {}) if isinstance(raw.get("parameters"), Mapping) else {},
            boundary_conditions=tuple(dict(item) for item in raw.get("boundary_conditions") or () if isinstance(item, Mapping)),
            requested_outputs=tuple(
                RequestedOutput.from_dict(item)
                for item in raw.get("requested_outputs") or ()
                if isinstance(item, Mapping)
            ),
            simulation_options=dict(raw.get("simulation_options") or {}) if isinstance(raw.get("simulation_options"), Mapping) else {},
            source_payload=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "model_domain": self.model_domain,
            "components": [
                {"id": item.id, "type": item.type, "parameters": {name: asdict(value) for name, value in item.parameters.items()}}
                for item in self.components
            ],
            "connections": [asdict(item) for item in self.connections],
            "parameters": dict(self.parameters),
            "boundary_conditions": [dict(item) for item in self.boundary_conditions],
            "requested_outputs": [item.to_dict() for item in self.requested_outputs],
            "simulation_options": dict(self.simulation_options),
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


__all__ = ["IRComponent", "IRConnection", "ModelIR", "ParameterValue", "RequestedOutput"]
