from __future__ import annotations

from .contracts import PropertyDataPoint


def linear_interpolate(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x1 == x0:
        raise ValueError("Cannot interpolate with identical x values")
    return float(y0 + (x - x0) * (y1 - y0) / (x1 - x0))


def build_temperature_interpolation(
    *,
    lower: PropertyDataPoint,
    upper: PropertyDataPoint,
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
            "source": lower.source_dict(),
        },
        "upper_point": {
            "temperature_c": upper.temperature_c,
            "value": upper.value,
            "unit": upper.unit,
            "source": upper.source_dict(),
        },
    }


__all__ = ["build_temperature_interpolation", "linear_interpolate"]
