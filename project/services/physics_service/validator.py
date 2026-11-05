"""Deterministic checks independent of language models and external solvers."""
from __future__ import annotations

from math import isfinite

from .contracts import PhysicsIssue, PhysicsValidationRequest, PhysicsValidationResult


def validate_physics(request: PhysicsValidationRequest) -> PhysicsValidationResult:
    issues: list[PhysicsIssue] = []

    def issue(code: str, field: str, message: str) -> None:
        issues.append(PhysicsIssue(code=code, field=field, message=message))

    def finite(value: float | int, field: str) -> bool:
        try:
            valid = isfinite(float(value))
        except (OverflowError, ValueError, TypeError):
            valid = False
        if not valid:
            issue("NON_FINITE_VALUE", field, "Value must be a finite number.")
        return valid

    for quantity in request.quantities:
        if not finite(quantity.value, quantity.name):
            continue
        value = float(quantity.value)
        absolute_zero = {"K": 0.0, "degC": -273.15}.get(quantity.unit) if quantity.quantity_type == "absolute_temperature" else None
        if absolute_zero is not None and value < absolute_zero:
            issue("BELOW_ABSOLUTE_ZERO", quantity.name, "Absolute temperature is below absolute zero.")
        if quantity.positive and value <= 0:
            issue("NOT_POSITIVE", quantity.name, "Value must be strictly positive.")
        if quantity.minimum is not None and value < quantity.minimum:
            issue("BELOW_MINIMUM", quantity.name, "Value is below the supplied minimum in the stated unit.")
        if quantity.maximum is not None and value > quantity.maximum:
            issue("ABOVE_MAXIMUM", quantity.name, "Value exceeds the supplied maximum in the stated unit.")

    relative_error = None
    balance = request.energy_balance
    if balance is not None:
        valid_in = finite(balance.heat_input_w, "energy_balance.heat_input_w")
        valid_out = finite(balance.heat_output_w, "energy_balance.heat_output_w")
        if valid_in and valid_out:
            heat_in, heat_out = float(balance.heat_input_w), float(balance.heat_output_w)
            scale = max(abs(heat_in), abs(heat_out))
            # Normalize before subtracting: finite opposite extremes cannot overflow.
            relative_error = abs(heat_in / scale - heat_out / scale) if scale else 0.0
            absolute_error = abs(heat_in - heat_out)
            if absolute_error > balance.absolute_tolerance_w and relative_error > balance.relative_tolerance:
                issue("ENERGY_IMBALANCE", "energy_balance", "Steady energy balance exceeds both supplied tolerances.")

    return PhysicsValidationResult(
        passed=not issues,
        status="failed" if issues else "passed",
        checked_quantity_count=len(request.quantities),
        energy_balance_checked=balance is not None,
        energy_relative_error=relative_error,
        issues=issues,
    )
