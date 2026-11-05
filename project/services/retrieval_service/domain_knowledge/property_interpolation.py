from __future__ import annotations

from .property_schemas import FluidPropertyPoint


def linear_interpolate(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x0 == x1:
        raise ValueError("Cannot interpolate between identical temperature points")
    return float(y0 + (x - x0) * (y1 - y0) / (x1 - x0))


def build_linear_temperature_interpolation(
    *,
    lower: FluidPropertyPoint,
    upper: FluidPropertyPoint,
    target_temperature_c: float,
    value: float,
) -> dict[str, object]:
    return {
        "method": "linear_temperature",
        "temperature_c": target_temperature_c,
        "value": value,
        "lower_point": {
            "temperature_c": lower.temperature_c,
            "value": lower.value,
            "unit": lower.unit,
            "source_id": lower.source_id,
            "source_status": lower.source_status,
        },
        "upper_point": {
            "temperature_c": upper.temperature_c,
            "value": upper.value,
            "unit": upper.unit,
            "source_id": upper.source_id,
            "source_status": upper.source_status,
        },
    }


__all__ = ["build_linear_temperature_interpolation", "linear_interpolate"]
