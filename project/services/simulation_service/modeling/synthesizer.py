from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping, Protocol

from .model_ir import ModelIR
from .registry import ComponentRegistry
from .thermal_network import (
    build_branched_network,
    build_conduction_convection_network,
    build_layered_network,
    build_series_network,
    with_requested_outputs,
)


@dataclass(frozen=True)
class SynthesisResult:
    status: str
    model_ir: ModelIR | None
    missing_parameters: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    synthesizer: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model_ir": self.model_ir.to_dict() if self.model_ir else None,
            "missing_parameters": list(self.missing_parameters),
            "warnings": list(self.warnings),
            "synthesizer": self.synthesizer,
        }


class ModelSynthesizer(Protocol):
    def synthesize(self, requirement: str | Mapping[str, Any]) -> SynthesisResult: ...


class FakeModelSynthesizer:
    """Deterministic no-network synthesizer for tests and contract fixtures."""

    def __init__(self, fixture: Mapping[str, Any], *, missing_parameters: tuple[str, ...] = ()) -> None:
        self._fixture = deepcopy(dict(fixture))
        self._missing = tuple(missing_parameters)

    def synthesize(self, requirement: str | Mapping[str, Any]) -> SynthesisResult:
        model = ModelIR.from_dict(deepcopy(self._fixture))
        return SynthesisResult(
            status="needs_input" if self._missing else "candidate",
            model_ir=model,
            missing_parameters=self._missing,
            synthesizer="fake_deterministic",
        )


class RuleBasedModelSynthesizer:
    """Small deterministic fallback for reviewed thermal primitives.

    It recognizes component vocabulary and explicit engineering values. It does
    not invent critical values and does not produce MATLAB source or commands.
    """

    def __init__(self, registry: ComponentRegistry) -> None:
        self.registry = registry

    def synthesize(self, requirement: str | Mapping[str, Any]) -> SynthesisResult:
        if isinstance(requirement, Mapping):
            return self._synthesize_structured(requirement)
        text = str(requirement or "").strip()
        if text.startswith("{"):
            try:
                structured = json.loads(text)
            except (TypeError, ValueError):
                structured = None
            if isinstance(structured, Mapping):
                return self._synthesize_structured(structured)
        generalized = _parse_generalized_requirement(text)
        if generalized is not None:
            return self._synthesize_structured(generalized)
        types = self._component_types(text)
        if not types:
            return SynthesisResult(
                status="unsupported",
                model_ir=None,
                warnings=("No reviewed component vocabulary was recognized.",),
                synthesizer="rule_based_fallback",
            )
        components: list[dict[str, Any]] = []
        missing: list[str] = []
        counters: dict[str, int] = {}
        for component_type in types:
            counters[component_type] = counters.get(component_type, 0) + 1
            component_id = _component_id(component_type, counters[component_type])
            parameters, component_missing = self._parameters(component_type, text)
            components.append({"id": component_id, "type": component_type, "parameters": parameters})
            missing.extend(component_missing)

        if not any(item["type"] == "thermal_reference" for item in components):
            components.append({"id": "thermal_reference_1", "type": "thermal_reference", "parameters": {}})
        if not any(item["type"] == "solver_configuration" for item in components):
            components.append({"id": "solver_configuration_1", "type": "solver_configuration", "parameters": {}})

        connections = _thermal_connections(components)
        source = next((item for item in components if item["type"] == "temperature_source"), None)
        output_component = next(
            (item for item in components if item["type"] in {"thermal_resistance", "convective_heat_transfer", "thermal_mass"}),
            source,
        )
        output_type = (
            "temperature"
            if output_component and output_component["type"] in {"thermal_mass", "temperature_source"}
            else "heat_flow"
        )
        payload = {
            "schema_version": "1.0",
            "model_id": "generated_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
            "model_domain": "thermal",
            "components": components,
            "connections": connections,
            "parameters": {},
            "boundary_conditions": ([{"component_id": source["id"], "kind": "temperature"}] if source else []),
            "requested_outputs": ([{
                "id": f"{output_component['id']}_{output_type}",
                "type": output_type,
                "source_component_id": output_component["id"],
            }] if output_component else []),
            "simulation_options": {"stop_time_s": 10.0, "max_result_signals": 4},
        }
        return SynthesisResult(
            status="needs_input" if missing else "candidate",
            model_ir=ModelIR.from_dict(payload),
            missing_parameters=tuple(dict.fromkeys(missing)),
            synthesizer="rule_based_fallback",
        )

    def _synthesize_structured(self, requirement: Mapping[str, Any]) -> SynthesisResult:
        payload = dict(requirement)
        topology = str(payload.get("topology") or "").strip().casefold()
        required_by_topology = {
            "series": ("resistances_k_w", "hot_temperature_k", "cold_temperature_k"),
            "layered_conduction": ("layers", "hot_temperature_k", "cold_temperature_k"),
            "branched": (
                "upstream_resistances_k_w", "branch_resistances_k_w",
                "downstream_resistances_k_w", "hot_temperature_k", "cold_temperature_k",
            ),
            "conduction_convection": (
                "resistances_k_w", "convection_coefficient_w_m2k", "convection_area_m2",
                "hot_temperature_k", "ambient_temperature_k",
            ),
        }
        if topology not in required_by_topology:
            return SynthesisResult(
                status="unsupported", model_ir=None,
                warnings=("Structured topology is outside the reviewed thermal family.",),
                synthesizer="rule_based_structured",
            )
        missing = tuple(
            name for name in required_by_topology[topology]
            if name not in payload or payload[name] is None
        )
        if missing:
            return SynthesisResult(
                status="needs_input", model_ir=None, missing_parameters=missing,
                synthesizer="rule_based_structured",
            )
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        model_id = str(payload.get("model_id") or f"structured_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}")
        try:
            if topology == "series":
                model = build_series_network(
                    model_id=model_id,
                    resistances_k_w=payload["resistances_k_w"],
                    hot_temperature_k=float(payload["hot_temperature_k"]),
                    cold_temperature_k=float(payload["cold_temperature_k"]),
                )
            elif topology == "layered_conduction":
                model = build_layered_network(
                    model_id=model_id,
                    layers=payload["layers"],
                    hot_temperature_k=float(payload["hot_temperature_k"]),
                    cold_temperature_k=float(payload["cold_temperature_k"]),
                )
            elif topology == "branched":
                model = build_branched_network(
                    model_id=model_id,
                    upstream_resistances_k_w=payload["upstream_resistances_k_w"],
                    branch_resistances_k_w=payload["branch_resistances_k_w"],
                    downstream_resistances_k_w=payload["downstream_resistances_k_w"],
                    hot_temperature_k=float(payload["hot_temperature_k"]),
                    cold_temperature_k=float(payload["cold_temperature_k"]),
                )
            else:
                model = build_conduction_convection_network(
                    model_id=model_id,
                    resistances_k_w=payload["resistances_k_w"],
                    convection_coefficient_w_m2k=float(payload["convection_coefficient_w_m2k"]),
                    convection_area_m2=float(payload["convection_area_m2"]),
                    hot_temperature_k=float(payload["hot_temperature_k"]),
                    ambient_temperature_k=float(payload["ambient_temperature_k"]),
                )
            outputs = payload.get("requested_outputs")
            if isinstance(outputs, (list, tuple)):
                model = with_requested_outputs(model, [item for item in outputs if isinstance(item, Mapping)])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            return SynthesisResult(
                status="needs_input", model_ir=None,
                missing_parameters=("invalid_structured_requirement",),
                warnings=(type(exc).__name__,),
                synthesizer="rule_based_structured",
            )
        return SynthesisResult(
            status="candidate", model_ir=model, synthesizer="rule_based_structured",
        )

    @staticmethod
    def _component_types(text: str) -> list[str]:
        vocabulary = (
            ("temperature_source", ("温度源", "温度边界", "temperature source")),
            ("thermal_resistance", ("热阻", "thermal resistance", "导热层")),
            ("thermal_mass", ("热容", "热质量", "thermal mass")),
            ("convective_heat_transfer", ("对流", "convective heat transfer")),
        )
        found: list[tuple[int, str]] = []
        lowered = text.casefold()
        for component_type, tokens in vocabulary:
            positions = [lowered.find(token.casefold()) for token in tokens if token.casefold() in lowered]
            if positions:
                found.append((min(positions), component_type))
        return [component_type for _position, component_type in sorted(found)]

    @staticmethod
    def _parameters(component_type: str, text: str) -> tuple[dict[str, Any], list[str]]:
        if component_type == "temperature_source":
            match = re.search(r"(?:温度|temperature)\s*(?:为|是|=|:|：)?\s*([-+]?\d+(?:\.\d+)?)\s*(K|℃|°C|degC)", text, re.IGNORECASE)
            if not match:
                return {}, ["temperature_source.temperature_k"]
            unit = "K" if match.group(2).upper() == "K" else "degC"
            return {"temperature_k": {"value": float(match.group(1)), "unit": unit}}, []
        if component_type == "thermal_resistance":
            match = re.search(r"(?:热阻|thermal\s+resistance)\s*(?:为|是|=|:|：)?\s*([-+]?\d+(?:\.\d+)?)\s*K\s*/\s*W", text, re.IGNORECASE)
            if not match:
                return {}, ["thermal_resistance.resistance_k_w"]
            return {"resistance_k_w": {"value": float(match.group(1)), "unit": "K/W"}}, []
        if component_type == "thermal_mass":
            mass = re.search(r"(?:质量|mass)\s*(?:为|是|=|:|：)?\s*([-+]?\d+(?:\.\d+)?)\s*(kg|g)", text, re.IGNORECASE)
            cp = re.search(r"(?:比热容|specific\s+heat(?:\s+capacity)?)\s*(?:为|是|=|:|：)?\s*([-+]?\d+(?:\.\d+)?)\s*J\s*/\s*\(?\s*(?:kg\s*\*\s*K|K\s*\*\s*kg)\s*\)?", text, re.IGNORECASE)
            params: dict[str, Any] = {}
            missing: list[str] = []
            if mass:
                params["mass_kg"] = {"value": float(mass.group(1)), "unit": mass.group(2).lower()}
            else:
                missing.append("thermal_mass.mass_kg")
            if cp:
                params["specific_heat_j_kgk"] = {"value": float(cp.group(1)), "unit": "J/(kg*K)"}
            else:
                missing.append("thermal_mass.specific_heat_j_kgk")
            return params, missing
        if component_type == "convective_heat_transfer":
            area = re.search(r"(?:面积|area)\s*(?:为|是|=|:|：)?\s*([-+]?\d+(?:\.\d+)?)\s*(m2|m\^2|cm\^2)", text, re.IGNORECASE)
            htc = re.search(r"(?:换热系数|对流系数|h)\s*(?:为|是|=|:|：)?\s*([-+]?\d+(?:\.\d+)?)\s*W\s*/\s*\(?m(?:2|\^2)\s*\*\s*K\)?", text, re.IGNORECASE)
            params = {}
            missing = []
            if area:
                params["area_m2"] = {"value": float(area.group(1)), "unit": area.group(2)}
            else:
                missing.append("convective_heat_transfer.area_m2")
            if htc:
                params["heat_transfer_coefficient_w_m2k"] = {"value": float(htc.group(1)), "unit": "W/(m^2*K)"}
            else:
                missing.append("convective_heat_transfer.heat_transfer_coefficient_w_m2k")
            return params, missing
        return {}, []


def _component_id(component_type: str, index: int) -> str:
    return f"{component_type}_{index}"


def _thermal_connections(components: list[dict[str, Any]]) -> list[dict[str, str]]:
    source = next((item for item in components if item["type"] == "temperature_source"), None)
    reference = next(item for item in components if item["type"] == "thermal_reference")
    solver = next(item for item in components if item["type"] == "solver_configuration")
    elements = [item for item in components if item["type"] in {"thermal_resistance", "convective_heat_transfer", "thermal_mass"}]
    connections: list[dict[str, str]] = []
    if source and elements:
        first = elements[0]
        first_port = "M" if first["type"] == "thermal_mass" else "A"
        connections.append(_connection(source["id"], "A", first["id"], first_port))
        current = first
        for following in elements[1:]:
            current_port = "M" if current["type"] == "thermal_mass" else "B"
            following_port = "M" if following["type"] == "thermal_mass" else "A"
            connections.append(_connection(current["id"], current_port, following["id"], following_port))
            current = following
        current_port = "M" if current["type"] == "thermal_mass" else "B"
        connections.append(_connection(current["id"], current_port, reference["id"], "H"))
        connections.append(_connection(solver["id"], "network", reference["id"], "H"))
    return connections


def _connection(left: str, left_port: str, right: str, right_port: str) -> dict[str, str]:
    return {"from_component": left, "from_port": left_port, "to_component": right, "to_port": right_port}


def _parse_generalized_requirement(text: str) -> dict[str, Any] | None:
    lowered = text.casefold()
    if not any(token in lowered for token in ("并联", "parallel", "分成", "分为", "分流", "split")):
        return None
    hot = _named_temperature(text, ("热端", "hot"))
    cold = _named_temperature(text, ("冷端", "cold"))
    split = re.search(
        r"分成|分为|分流|(?:[两二三四五六七八]|\d+)\s*(?:条|个|路|支)?\s*并联|(?:\d+\s+)?parallel(?:\s+thermal\s+resistance)?\s+branches?",
        text,
        re.IGNORECASE,
    )
    merge = re.search(r"合流|汇合|汇流|并联后|merge|rejoin|combine", text, re.IGNORECASE)
    if split:
        upstream_text = text[:split.start()]
        branch_text = text[split.start():merge.start() if merge and merge.start() > split.start() else len(text)]
        downstream_text = text[merge.start():] if merge and merge.start() > split.start() else ""
    else:
        upstream_text = _section(text, ("上游", "upstream"), ("并联", "parallel"))
        branch_text = _section(text, ("并联", "parallel"), ("下游", "downstream"))
        downstream_text = _section(text, ("下游", "downstream"), ("输出", "output"), allow_end=True)
    upstream = _resistance_values(upstream_text)
    branches = _resistance_values(branch_text)
    downstream = _resistance_values(downstream_text)
    required = {
        "hot_temperature_k": hot,
        "cold_temperature_k": cold,
        "upstream_resistances_k_w": upstream,
        "branch_resistances_k_w": [[value] for value in branches] if len(branches) >= 2 else None,
        "downstream_resistances_k_w": downstream,
    }
    result: dict[str, Any] = {"topology": "branched", **required}
    if all(value is not None for value in required.values()):
        source_id = "upstream_1" if upstream else "branch_1_1"
        outputs = [{
            "id": "source_heat_flow", "type": "heat_flow",
            "source_component_id": source_id, "source_port": "A",
        }]
        if re.search(r"中间温度|节点温度|intermediate\s+temperature|node\s+temperature", text, re.IGNORECASE):
            outputs.append({
                "id": "split_temperature", "type": "temperature",
                "source_component_id": "branch_1_1", "source_port": "B",
            })
        if re.search(r"边界热流|出口热流|boundary\s+heat\s+flow|outlet\s+heat\s+flow", text, re.IGNORECASE):
            boundary_source = f"downstream_{len(downstream)}" if downstream else "branch_1_1"
            outputs.append({
                "id": "boundary_heat_flow", "type": "heat_flow",
                "source_component_id": boundary_source, "source_port": "B",
            })
        result["requested_outputs"] = outputs
    return result


def _named_temperature(text: str, names: tuple[str, ...]) -> float | None:
    names_pattern = "|".join(re.escape(name) for name in names)
    match = re.search(
        rf"(?:{names_pattern})\s*(?:温度|temperature)?\s*(?:为|是|=|:|：)?\s*"
        rf"([-+]?\d+(?:\.\d+)?)\s*(K|℃|°C|degC)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    return value if match.group(2).casefold() == "k" else value + 273.15


def _section(
    text: str,
    starts: tuple[str, ...],
    ends: tuple[str, ...],
    *,
    allow_end: bool = False,
) -> str:
    start_pattern = "|".join(re.escape(value) for value in starts)
    end_pattern = "|".join(re.escape(value) for value in ends)
    suffix = "$" if allow_end else r"(?!)"
    match = re.search(
        rf"(?:{start_pattern})(.*?)(?=(?:{end_pattern})|{suffix})",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _resistance_values(text: str) -> list[float]:
    if not re.search(r"K\s*/\s*W", text, re.IGNORECASE):
        return []
    without_counts = re.sub(r"(?<![\d.])\d+\s*(?:条|个|路|支)(?=\s|热|并|通|支|路|$)", "", text)
    without_counts = re.sub(
        r"\b\d+\s+(?:parallel\s+)?(?:thermal\s+resistance\s+)?branches?\b",
        "",
        without_counts,
        flags=re.IGNORECASE,
    )
    unit_matches = list(re.finditer(r"K\s*/\s*W", without_counts, re.IGNORECASE))
    values: list[float] = []
    for number in re.finditer(r"[-+]?\d+(?:\.\d+)?", without_counts):
        unit = next((item for item in unit_matches if item.start() >= number.end()), None)
        if unit is None:
            continue
        between = without_counts[number.end():unit.start()]
        # A value belongs to this K/W unit only when the intervening text is a
        # numeric list connector. This accepts compact Chinese/English numeric
        # lists without swallowing earlier temperatures or branch counts.
        remainder = re.sub(r"(?:and|or|to|和|与|及)", "", between, flags=re.IGNORECASE)
        if re.fullmatch(r"[\s、,，/&+\-–—.\d]*", remainder):
            values.append(float(number.group(0)))
    return values


__all__ = ["FakeModelSynthesizer", "ModelSynthesizer", "RuleBasedModelSynthesizer", "SynthesisResult"]
