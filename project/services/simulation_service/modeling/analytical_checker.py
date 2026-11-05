from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from .model_ir import ModelIR, ParameterValue
from .thermal_network_solver import ThermalNetworkReferenceSolver


def compare_numeric(
    expected: float,
    actual: float,
    *,
    relative_tolerance: float = 1e-3,
    absolute_tolerance: float = 1e-6,
) -> dict[str, Any]:
    expected_value = float(expected)
    actual_value = float(actual)
    if not isfinite(expected_value) or not isfinite(actual_value):
        return {
            "expected": expected_value if isfinite(expected_value) else None,
            "actual": actual_value if isfinite(actual_value) else None,
            "absolute_error": None,
            "relative_error": None,
            "tolerance": max(float(absolute_tolerance), 0.0),
            "passed": False,
        }
    absolute_error = abs(actual_value - expected_value)
    scale = abs(expected_value)
    tolerance = max(float(absolute_tolerance), float(relative_tolerance) * scale)
    relative_error = absolute_error / scale if scale > float(absolute_tolerance) else None
    return {
        "expected": expected_value,
        "actual": actual_value,
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "tolerance": tolerance,
        "passed": absolute_error <= tolerance,
    }


class ThermalAnalyticalChecker:
    """Independent topology-aware checks over logical IR and bounded results only."""

    checker_version = "thermal-analytical-checker-v2"

    def __init__(self, *, relative_tolerance: float = 1e-3, absolute_tolerance_w: float = 1e-6) -> None:
        self.relative_tolerance = float(relative_tolerance)
        self.absolute_tolerance_w = float(absolute_tolerance_w)

    def check(self, model: ModelIR, result: Mapping[str, Any]) -> dict[str, Any]:
        reference = ThermalNetworkReferenceSolver().solve(model)
        if reference.get("status") == "NOT_APPLICABLE":
            return self._not_applicable(str(reference.get("reason") or "Reference solver is not applicable."))
        if reference.get("status") != "PASS":
            return self._failure(
                str(reference.get("code") or "ANALYTICAL_REFERENCE_FAILED"),
                str(reference.get("reason") or "Independent reference solver failed."),
            )
        expected_outputs = reference.get("expected_outputs") or {}
        checks: dict[str, dict[str, Any]] = {}
        for requested in model.requested_outputs:
            expected = expected_outputs.get(requested.id)
            if not isinstance(expected, Mapping):
                return self._not_applicable(f"Requested output is outside the reference solver: {requested.id}")
            unit = str(expected.get("unit") or "")
            actual = _actual_output(result, requested.id, unit=unit)
            if actual is None:
                return self._failure(
                    "ANALYTICAL_ACTUAL_OUTPUT_INVALID",
                    f"A finite canonical value is required: {requested.id}",
                )
            actual_for_comparison = abs(actual) if requested.type == "heat_flow" else actual
            checks[requested.id] = compare_numeric(
                float(expected["value"]),
                actual_for_comparison,
                relative_tolerance=self.relative_tolerance,
                absolute_tolerance=self.absolute_tolerance_w,
            )
        if not checks:
            return self._not_applicable("No supported logical output was requested.")
        cross_check = next(iter(checks.values()))
        validation_method = str(reference.get("validation_method") or "BASIC_ONLY")
        formula = {
            "SERIES_RESISTANCE": (
                "Q = delta_temperature / thermal_resistance"
                if len([item for item in model.components if item.type == "thermal_resistance"]) == 1
                else "Q = delta_temperature / sum(thermal_resistance)"
            ),
            "LAYERED_CONDUCTION": "Q = delta_temperature / sum(thickness / (conductivity * area))",
            "NODAL_LINEAR": "sum(G_ij * (T_i - T_j)) = 0",
        }.get(validation_method)
        return {
            "checker_version": self.checker_version,
            "status": "PASS" if all(item["passed"] for item in checks.values()) else "FAIL",
            "validation_method": validation_method,
            "formula": formula,
            "cross_check": cross_check,
            "cross_checks": checks,
            "reason": "independent_closed_form_check",
        }

    def _not_applicable(self, reason: str) -> dict[str, Any]:
        return {
            "checker_version": self.checker_version,
            "status": "NOT_APPLICABLE",
            "validation_method": "BASIC_ONLY",
            "formula": None,
            "cross_check": None,
            "reason": reason,
        }

    def _failure(self, code: str, reason: str) -> dict[str, Any]:
        return {
            "checker_version": self.checker_version,
            "status": "FAIL",
            "validation_method": "BASIC_ONLY",
            "formula": "Q = delta_temperature / thermal_resistance",
            "cross_check": None,
            "code": code,
            "reason": reason,
        }


def _positive_parameter(parameter: ParameterValue | None, unit: str) -> float | None:
    if parameter is None or parameter.unit != unit or isinstance(parameter.value, bool):
        return None
    if not isinstance(parameter.value, (int, float)):
        return None
    value = float(parameter.value)
    return value if isfinite(value) and value > 0.0 else None


def _absolute_temperature(parameter: ParameterValue | None) -> float | None:
    if parameter is None or isinstance(parameter.value, bool) or not isinstance(parameter.value, (int, float)):
        return None
    value = float(parameter.value)
    if parameter.unit in {"degC", "°C"}:
        value += 273.15
    elif parameter.unit != "K":
        return None
    return value if isfinite(value) and value > 0.0 else None


def _actual_output(result: Mapping[str, Any], logical_output_id: str, *, unit: str) -> float | None:
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    item = next(
        (
            value for value in outputs
            if isinstance(value, Mapping) and value.get("logical_output_id") == logical_output_id
        ),
        None,
    )
    if item is None or item.get("status") != "ok" or item.get("unit") != unit:
        return None
    raw = item.get("value")
    if raw is None:
        series = item.get("series") if isinstance(item.get("series"), list) else []
        raw = series[-1].get("value") if series and isinstance(series[-1], Mapping) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if isfinite(value) else None


__all__ = ["ThermalAnalyticalChecker", "compare_numeric"]
