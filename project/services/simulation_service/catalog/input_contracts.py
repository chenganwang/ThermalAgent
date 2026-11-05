"""Reviewed engineering input normalization, independent of solver lifecycle."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose, isfinite
from typing import Any, Mapping

from .schemas import ModelDefinition


PLANE_WALL_CANONICAL_INPUTS = (
    "thickness_m", "thermal_conductivity_w_mk", "area_m2", "delta_temperature_k",
)


@dataclass
class ModelInputResult:
    inputs: dict[str, Any] = field(default_factory=dict)
    canonical_inputs: dict[str, Any] = field(default_factory=dict)
    missing_inputs: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    normalizations: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.missing_inputs and not self.errors


def normalize_model_inputs(model: ModelDefinition, inputs: Mapping[str, Any]) -> ModelInputResult:
    result = ModelInputResult()
    if not isinstance(inputs, Mapping):
        result.errors.append({"code": "SIMULATION_INPUTS_INVALID", "field": "inputs", "message": "Inputs must be an object."})
        return result
    # allowed_inputs belongs to the legacy scenario form API. The conversational
    # plane-wall contract declares its canonical fields separately.
    allowed = set(model.required_inputs) | set(model.optional_inputs)
    allowed.update(name for group in model.alternative_input_groups for option in group["any_of"] for name in option)
    if model.model_id != "plane_wall_steady_v1":
        allowed.update(model.allowed_inputs)
    for name, value in inputs.items():
        if name not in allowed:
            result.errors.append({"code": "SIMULATION_INPUTS_INVALID", "field": str(name), "message": "Unknown model input."})
        elif value is not None:
            result.inputs[name] = value
    if model.model_id == "plane_wall_steady_v1":
        _normalize_plane_wall(result)
        result.canonical_inputs = {key: result.inputs[key] for key in PLANE_WALL_CANONICAL_INPUTS if key in result.inputs}
    else:
        result.canonical_inputs = dict(result.inputs)
    result.missing_inputs = model.missing_inputs(result.inputs)
    return result


def _normalize_plane_wall(result: ModelInputResult) -> None:
    for name, value in list(result.inputs.items()):
        try:
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            result.errors.append({"code": "SIMULATION_INPUTS_INVALID", "field": name, "message": "Expected a finite number."})
            del result.inputs[name]
        else:
            result.inputs[name] = float(value)
    for name in PLANE_WALL_CANONICAL_INPUTS[:3]:
        if name in result.inputs and result.inputs[name] <= 0:
            result.errors.append({"code": "SIMULATION_INPUTS_INVALID", "field": name, "message": "Must be greater than zero."})
    pair = ("hot_temperature_c", "cold_temperature_c")
    if all(name in result.inputs for name in pair):
        difference = abs(result.inputs[pair[0]] - result.inputs[pair[1]])
        if not isfinite(difference):
            result.errors.append({"code": "SIMULATION_INPUTS_INVALID", "field": "temperature_boundary", "message": "Temperature difference must be finite."})
            return
        supplied = result.inputs.get("delta_temperature_k")
        if supplied is not None and not isclose(supplied, difference, rel_tol=1e-9, abs_tol=1e-9):
            result.errors.append({
                "code": "SIMULATION_INPUT_CONFLICT", "field": "temperature_boundary",
                "message": "Explicit temperature difference disagrees with the hot/cold pair; revise the inputs.",
                "provided_delta_temperature_k": supplied, "derived_delta_temperature_k": difference,
            })
        elif supplied is None:
            result.inputs["delta_temperature_k"] = difference
            result.normalizations["delta_temperature_k"] = {
                "value": difference, "canonical_unit": "K", "raw_unit": "degC",
                "source_inputs": {name: result.inputs[name] for name in pair},
                "normalization": "absolute_hot_cold_difference",
            }
    difference = result.inputs.get("delta_temperature_k")
    if difference is not None and (not isfinite(difference) or not 0 <= difference <= 5000):
        result.errors.append({"code": "SIMULATION_INPUTS_INVALID", "field": "delta_temperature_k", "message": "Temperature difference must be between 0 and 5000 K."})
