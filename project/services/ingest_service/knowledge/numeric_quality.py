"""Bounded arithmetic and dimensional QC for explicitly supplied numeric specs.

This module does not interpret OCR expressions, infer missing conditions, query a
model, or establish that a source supports a claim. ``passed`` means only that
the explicit calculation and optional expected value pass the checks below.
Source applicability, original numbers and domain interpretation require review.
Units are an intentionally small, case-sensitive allowlist, not a unit parser.
Affine temperatures are unsupported; K in uncertainty operations is a difference.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any


SCHEMA_VERSION = "explicit-numeric-quality-v1"
# Exponents of kg, m, s, K. No string evaluation or expression compilation occurs.
Dimension = tuple[int, int, int, int]
DIMENSIONLESS: Dimension = (0, 0, 0, 0)
ENERGY: Dimension = (1, 2, -2, 0)
VOLUME: Dimension = (0, 3, 0, 0)
WATER_PER_ENERGY: Dimension = (-1, 1, 2, 0)


@dataclass(frozen=True)
class Unit:
    symbol: str
    scale: float
    dimension: Dimension


def _unit_table() -> dict[str, Unit]:
    definitions = [
        ("1", 1.0, DIMENSIONLESS, ("dimensionless",)),
        ("K", 1.0, (0, 0, 0, 1), ()),
        ("W", 1.0, (1, 2, -3, 0), ()),
        ("mW", 1e-3, (1, 2, -3, 0), ()),
        ("kW", 1e3, (1, 2, -3, 0), ()),
        ("MW", 1e6, (1, 2, -3, 0), ()),
        ("Pa", 1.0, (1, -1, -2, 0), ()),
        ("kPa", 1e3, (1, -1, -2, 0), ()),
        ("MPa", 1e6, (1, -1, -2, 0), ()),
        ("Pa*s", 1.0, (1, -1, -1, 0), ("Pa·s",)),
        ("mPa*s", 1e-3, (1, -1, -1, 0), ("mPa·s",)),
        ("uPa*s", 1e-6, (1, -1, -1, 0),
         ("uPa·s", "μPa*s", "μPa·s", "µPa*s", "µPa·s")),
        ("J", 1.0, ENERGY, ()),
        ("kJ", 1e3, ENERGY, ()),
        ("MJ", 1e6, ENERGY, ()),
        ("Wh", 3600.0, ENERGY, ()),
        ("kWh", 3.6e6, ENERGY, ()),
        ("MWh", 3.6e9, ENERGY, ()),
        ("J/kg", 1.0, (0, 2, -2, 0), ()),
        ("kJ/kg", 1e3, (0, 2, -2, 0), ()),
        ("J/(kg*K)", 1.0, (0, 2, -2, -1),
         ("J/(kg·K)", "J/(kg K)")),
        ("kJ/(kg*K)", 1e3, (0, 2, -2, -1),
         ("kJ/(kg·K)", "kJ/(kg K)")),
        ("m3", 1.0, VOLUME, ("m³",)),
        ("L", 1e-3, VOLUME, ()),
        ("m3/J", 1.0, WATER_PER_ENERGY, ("m³/J",)),
        ("L/kWh", 1e-3 / 3.6e6, WATER_PER_ENERGY, ()),
        ("m3/kWh", 1.0 / 3.6e6, WATER_PER_ENERGY, ("m³/kWh",)),
    ]
    return {name: Unit(symbol, scale, dim)
            for symbol, scale, dim, aliases in definitions
            for name in (symbol, *aliases)}


UNITS = _unit_table()
OPERATIONS = frozenset({"rss", "rectangular_standard_uncertainty",
    "triangular_standard_uncertainty", "expanded_to_standard_uncertainty",
    "standard_to_expanded_uncertainty", "unit_conversion", "pue", "wue"})


class _Unavailable(ValueError):
    """Supported evidence is absent, so no arithmetic decision can be made."""


class _Failed(ValueError):
    """An explicit specification contradicts the numeric/dimensional contract."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Failed(f"{label}:finite_number_required")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise _Failed(f"{label}:finite_number_required") from None
    if not math.isfinite(number):
        raise _Failed(f"{label}:finite_number_required")
    return number


def _unit(symbol: Any) -> Unit:
    if not isinstance(symbol, str) or symbol not in UNITS:
        raise _Unavailable("unsupported_unit")
    return UNITS[symbol]


def _quantity(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"value", "unit"}:
        raise _Failed(f"{label}:quantity_requires_value_and_unit")
    number = _finite(value["value"], label)
    unit = _unit(value["unit"])
    si_value = _finite(number * unit.scale, f"{label}:SI_value")
    if number != 0.0 and si_value == 0.0:
        raise _Failed(f"{label}:conversion_underflow")
    return {"value": number, "unit": unit.symbol, "SI_value": si_value,
            "dimension": list(unit.dimension)}


def _require_keys(inputs: Mapping, keys: set[str]) -> None:
    if set(inputs) != keys:
        raise _Failed("unexpected_or_missing_input_variables")


def _dimension(value: Mapping, expected: Dimension) -> None:
    if tuple(value["dimension"]) != expected:
        raise _Failed("dimension_mismatch")


def _assumptions(spec: Mapping, names: tuple[str, ...]) -> None:
    assumptions = spec.get("assumptions", {})
    if not isinstance(assumptions, Mapping):
        raise _Failed("invalid_assumptions")
    if any(assumptions.get(name) is not True for name in names):
        raise _Unavailable("required_assumptions_not_confirmed")


def _nonnegative(value: float, label: str, *, positive: bool = False) -> None:
    if value < 0.0 or (positive and value == 0.0):
        raise _Failed(f"{label}:physical_domain_violation")


def _calculate(operation: str, inputs: dict, spec: Mapping) -> tuple[float, Dimension, str, str]:
    """Return SI value, dimensions, formula and default presentation unit."""
    if operation == "unit_conversion":
        _require_keys(inputs, {"value"})
        v = inputs["value"]
        return v["SI_value"], tuple(v["dimension"]), "y = x * input_scale / output_scale", v["unit"]
    if operation == "rss":
        if len(inputs) < 2:
            raise _Failed("rss_requires_at_least_two_contributions")
        dimension = tuple(next(iter(inputs.values()))["dimension"])
        for value in inputs.values():
            _dimension(value, dimension)
            _nonnegative(value["SI_value"], "uncertainty")
        _assumptions(spec, ("uncorrelated", "inputs_are_uncertainty_contributions"))
        # hypot avoids intermediate square overflow/underflow.
        return (math.hypot(*(v["SI_value"] for v in inputs.values())), dimension,
                "u_c = sqrt(sum(u_i**2)) [uncorrelated uncertainty contributions]",
                next(iter(inputs.values()))["unit"])
    if operation in {"rectangular_standard_uncertainty", "triangular_standard_uncertainty"}:
        _require_keys(inputs, {"a"})
        value = inputs["a"]
        _nonnegative(value["SI_value"], "half_width")
        divisor = 3 if operation == "rectangular_standard_uncertainty" else 6
        return (value["SI_value"] / math.sqrt(divisor), tuple(value["dimension"]),
                f"u = a / sqrt({divisor}) [a is distribution half-width]", value["unit"])
    if operation in {"expanded_to_standard_uncertainty", "standard_to_expanded_uncertainty"}:
        expanded = operation == "expanded_to_standard_uncertainty"
        name = "U" if expanded else "u"
        _require_keys(inputs, {name, "k"})
        value, coverage = inputs[name], inputs["k"]
        _dimension(coverage, DIMENSIONLESS)
        _nonnegative(value["SI_value"], "uncertainty")
        _nonnegative(coverage["SI_value"], "coverage_factor", positive=True)
        result = value["SI_value"] / coverage["SI_value"] if expanded else value["SI_value"] * coverage["SI_value"]
        return result, tuple(value["dimension"]), "u = U / k" if expanded else "U = k * u", value["unit"]
    if operation == "pue":
        _require_keys(inputs, {"facility_energy", "it_energy"})
        facility, it = inputs["facility_energy"], inputs["it_energy"]
        _dimension(facility, ENERGY)
        _dimension(it, ENERGY)
        _nonnegative(facility["SI_value"], "facility_energy")
        _nonnegative(it["SI_value"], "it_energy", positive=True)
        if facility["SI_value"] < it["SI_value"]:
            raise _Failed("facility_energy_less_than_it_energy")
        _assumptions(spec, ("same_period_and_boundary",))
        return facility["SI_value"] / it["SI_value"], DIMENSIONLESS, "PUE = facility_energy / it_energy", "1"
    _require_keys(inputs, {"water", "it_energy"})
    water, it = inputs["water"], inputs["it_energy"]
    _dimension(water, VOLUME)
    _dimension(it, ENERGY)
    _nonnegative(water["SI_value"], "water")
    _nonnegative(it["SI_value"], "it_energy", positive=True)
    _assumptions(spec, ("same_period_and_boundary",))
    return water["SI_value"] / it["SI_value"], WATER_PER_ENERGY, "WUE = water_volume / it_energy", "L/kWh"


def _compare_expected(computed: dict, expected: Any) -> dict:
    if not isinstance(expected, Mapping) or not {"value", "unit"} <= set(expected):
        raise _Failed("invalid_expected_quantity")
    if set(expected) - {"value", "unit", "rtol", "atol"}:
        raise _Failed("unexpected_expected_fields")
    reference = _quantity({"value": expected["value"], "unit": expected["unit"]}, "expected")
    _dimension(reference, tuple(computed["dimension"]))
    rtol = _finite(expected.get("rtol", 1e-9), "expected_rtol")
    atol = _finite(expected.get("atol", 0.0), "expected_atol")
    # Explicit absolute tolerance uses the expected unit, and is reported below.
    if not 0 <= rtol <= 1e-6 or atol < 0:
        raise _Failed("expected_tolerance_out_of_bounds")
    atol_si = _finite(atol * _unit(expected["unit"]).scale, "expected_atol_SI")
    match = math.isclose(computed["SI_value"], reference["SI_value"], rel_tol=rtol, abs_tol=atol_si)
    absolute_error = _finite(abs(computed["SI_value"] - reference["SI_value"]), "expected_absolute_error_SI")
    return {"status": "passed" if match else "failed", "expected": reference,
            "rtol": rtol, "atol": atol, "atol_unit": reference["unit"],
            "absolute_error_SI": absolute_error}


def evaluate_numeric_quality(spec: Mapping | None) -> dict[str, Any]:
    """Evaluate a bounded explicit specification; never award source correctness.

    Unknown operations/units and missing physical assumptions are unavailable;
    invalid numbers, dimensions, domains and expected mismatches fail. Expected
    comparisons default to rtol=1e-9, atol=0 to preserve tiny nonzero quantities.
    """
    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "status": "unavailable",
        "reason": "no_explicit_numeric_spec", "operation": None, "normalized_inputs": {},
        "formula": None, "computed": None, "expected_comparison": {"status": "not_supplied"},
        "source_support": "requires_review", "human_reviewed": False,
        "input_origin": "explicit_numeric_spec",
        "scope": "explicit_arithmetic_and_dimensions_only"}
    if spec is None:
        return result
    try:
        if not isinstance(spec, Mapping):
            raise _Failed("numeric_spec_must_be_object")
        operation = spec.get("operation")
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise _Unavailable("unsupported_operation")
        result["operation"] = operation
        provenance = spec.get("provenance", {})
        if not isinstance(provenance, Mapping):
            raise _Failed("invalid_provenance")
        origin = provenance.get("origin", "explicit_numeric_spec")
        if not isinstance(origin, str) or origin not in {"explicit_numeric_spec", "qa_arithmetic_spec", "explicit_source_variables"}:
            raise _Unavailable("unsupported_input_origin")
        result["input_origin"] = origin
        raw_inputs = spec.get("inputs")
        if not isinstance(raw_inputs, Mapping) or not raw_inputs or len(raw_inputs) > 256:
            raise _Failed("inputs_require_nonempty_bounded_object")
        if any(not isinstance(key, str) or not key for key in raw_inputs):
            raise _Failed("invalid_input_name")
        inputs = {key: _quantity(value, key) for key, value in raw_inputs.items()}
        result["normalized_inputs"] = inputs
        si_value, dimension, formula, default_unit = _calculate(operation, inputs, spec)
        result["formula"] = formula
        si_value = _finite(si_value, "computed_SI_value")
        nonzero_input = {
            "unit_conversion": "value", "rectangular_standard_uncertainty": "a",
            "triangular_standard_uncertainty": "a", "expanded_to_standard_uncertainty": "U",
            "standard_to_expanded_uncertainty": "u", "pue": "facility_energy", "wue": "water",
        }.get(operation)
        must_be_nonzero = (any(v["SI_value"] != 0.0 for v in inputs.values()) if operation == "rss"
                           else inputs[nonzero_input]["SI_value"] != 0.0)
        if must_be_nonzero and si_value == 0.0:
            raise _Failed("arithmetic_underflow")
        output = _unit(spec.get("output_unit", default_unit))
        if output.dimension != dimension:
            raise _Failed("output_dimension_mismatch")
        displayed = _finite(si_value / output.scale, "computed_value")
        if si_value != 0.0 and displayed == 0.0:
            raise _Failed("output_conversion_underflow")
        result["computed"] = {"value": displayed, "unit": output.symbol,
                              "SI_value": si_value, "dimension": list(dimension)}
        result.update(status="passed", reason="explicit_arithmetic_checks_passed")
        if "expected" in spec:
            try:
                comparison = _compare_expected(result["computed"], spec["expected"])
            except (_Unavailable, _Failed) as exc:
                result["expected_comparison"] = {
                    "status": "unavailable" if isinstance(exc, _Unavailable) else "failed",
                    "reason": str(exc)}
                raise
            result["expected_comparison"] = comparison
            if comparison["status"] == "failed":
                result.update(status="failed", reason="expected_value_mismatch")
    except _Unavailable as exc:
        result.update(status="unavailable", reason=str(exc))
    except _Failed as exc:
        result.update(status="failed", reason=str(exc))
    except (OverflowError, ZeroDivisionError):
        result.update(status="failed", reason="numeric_overflow_or_division_failure")
    return result


def assess_record_numeric_quality(record: Mapping) -> dict[str, Any]:
    """Read explicit specs only; generated formula annotations are never inputs."""
    if not isinstance(record, Mapping):
        return evaluate_numeric_quality([])
    present = [name for name in ("arithmetic_spec", "source_numeric_spec") if name in record]
    if not present:
        return evaluate_numeric_quality(None)
    if len(present) != 1:
        result = evaluate_numeric_quality(None)
        result.update(status="failed", reason="ambiguous_multiple_numeric_specs")
        return result
    name = present[0]
    spec = record[name]
    if isinstance(spec, Mapping):
        # Do not trust a caller-supplied origin or mutate the record/spec.
        spec = {**spec, "provenance": {"origin": "qa_arithmetic_spec" if name == "arithmetic_spec" else "explicit_source_variables"}}
    return evaluate_numeric_quality(spec)
