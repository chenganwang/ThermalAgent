from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from .schemas import ScenarioDefinition, ValidationResult


def validate_scenario_params(scenario: ScenarioDefinition, params: Mapping[str, Any] | None) -> ValidationResult:
    if not isinstance(params, Mapping):
        return ValidationResult(False, errors=[{"field": "params", "code": "must_be_object"}])
    schemas = {str(item["name"]): item for item in scenario.input_schema}
    unknown = sorted(str(key) for key in params if str(key) not in schemas)
    errors = [{"field": name, "code": "unknown_parameter"} for name in unknown]
    missing = [name for name, spec in schemas.items() if spec.get("required") and _missing(params.get(name))]
    normalized: dict[str, Any] = {}
    for name, value in params.items():
        if name not in schemas or _missing(value):
            continue
        result, item_errors = _normalize(value, schemas[name], name)
        errors.extend(item_errors)
        if not item_errors:
            normalized[name] = result
    _scenario_rules(scenario.scenario_id, normalized, errors)
    return ValidationResult(not missing and not errors, normalized, missing, errors)


def _normalize(value: Any, spec: Mapping[str, Any], field: str) -> tuple[Any, list[dict[str, str]]]:
    kind = str(spec.get("type") or "")
    if kind == "number":
        if isinstance(value, bool):
            return None, [{"field": field, "code": "must_be_number"}]
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None, [{"field": field, "code": "must_be_number"}]
        if not isfinite(number):
            return None, [{"field": field, "code": "must_be_finite"}]
        if "minimum_exclusive" in spec and number <= float(spec["minimum_exclusive"]):
            return None, [{"field": field, "code": "must_be_greater_than_minimum"}]
        if "minimum" in spec and number < float(spec["minimum"]):
            return None, [{"field": field, "code": "below_minimum"}]
        return number, []
    if kind == "string":
        if not isinstance(value, str):
            return None, [{"field": field, "code": "must_be_string"}]
        text = value.strip()
        if len(text) < int(spec.get("minimum_length") or 0):
            return None, [{"field": field, "code": "too_short"}]
        return text, []
    if kind == "array":
        if not isinstance(value, list):
            return None, [{"field": field, "code": "must_be_array"}]
        if len(value) < int(spec.get("minimum_items") or 0):
            return None, [{"field": field, "code": "too_few_items"}]
        item_spec = spec.get("items") or {}
        if item_spec.get("type") != "object":
            return list(value), []
        properties = {str(x["name"]): x for x in item_spec.get("properties") or ()}
        normalized_items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for index, item in enumerate(value):
            prefix = f"{field}[{index}]"
            if not isinstance(item, Mapping):
                errors.append({"field": prefix, "code": "must_be_object"})
                continue
            for key in item:
                if key not in properties:
                    errors.append({"field": f"{prefix}.{key}", "code": "unknown_parameter"})
            normalized_item: dict[str, Any] = {}
            for name, child in properties.items():
                if child.get("required") and _missing(item.get(name)):
                    errors.append({"field": f"{prefix}.{name}", "code": "missing_parameter"})
                    continue
                if not _missing(item.get(name)):
                    child_value, child_errors = _normalize(item[name], child, f"{prefix}.{name}")
                    errors.extend(child_errors)
                    if not child_errors:
                        normalized_item[name] = child_value
            normalized_items.append(normalized_item)
        return normalized_items, errors
    return None, [{"field": field, "code": "unsupported_schema_type"}]


def _scenario_rules(scenario_id: str, params: dict[str, Any], errors: list[dict[str, str]]) -> None:
    if scenario_id == "cylindrical_wall_steady_conduction" and {"inner_radius_m", "outer_radius_m"} <= params.keys():
        if params["outer_radius_m"] <= params["inner_radius_m"]:
            errors.append({"field": "outer_radius_m", "code": "must_exceed_inner_radius"})
    if scenario_id == "liquid_loop_energy_balance":
        supplied = [name for name in ("mass_flow_kg_s", "outlet_temperature_c", "allowed_temperature_rise_k") if name in params]
        if not supplied:
            errors.append({"field": "mass_flow_kg_s", "code": "one_solve_mode_parameter_required"})
        elif len(supplied) > 1:
            errors.append({"field": ",".join(supplied), "code": "ambiguous_solve_mode"})
        if "outlet_temperature_c" in params and "inlet_temperature_c" in params and params["outlet_temperature_c"] <= params["inlet_temperature_c"]:
            errors.append({"field": "outlet_temperature_c", "code": "must_exceed_inlet_temperature"})


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


__all__ = ["validate_scenario_params"]
