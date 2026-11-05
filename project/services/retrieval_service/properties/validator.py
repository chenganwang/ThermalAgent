from __future__ import annotations

from typing import Any


_REQUIRED_POINT_FIELDS = (
    "fluid",
    "property_name",
    "temperature_c",
    "value",
    "unit",
    "source_id",
    "source_title",
    "source_type",
    "source_quality",
    "validated",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_property_data(data: dict[str, Any], *, source_label: str = "<memory>") -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{source_label}: data must be a JSON object"]
    points = data.get("data_points")
    if points is None:
        errors.append(f"{source_label}: data_points must be present")
        points = []
    if not isinstance(points, list):
        errors.append(f"{source_label}: data_points must be a list")
        return errors

    for index, point in enumerate(points):
        label = f"{source_label}: data_points[{index}]"
        if not isinstance(point, dict):
            errors.append(f"{label}: point must be an object")
            continue
        for field in _REQUIRED_POINT_FIELDS:
            if field not in point or point.get(field) in ("", None):
                errors.append(f"{label}: {field} is required")
        if "temperature_c" in point and not _is_number(point.get("temperature_c")):
            errors.append(f"{label}: temperature_c must be numeric")
        if "value" in point and not _is_number(point.get("value")):
            errors.append(f"{label}: value must be numeric")
        concentration = point.get("concentration_percent")
        if concentration is not None and not _is_number(concentration):
            errors.append(f"{label}: concentration_percent must be numeric or null")
        if "validated" in point and not isinstance(point.get("validated"), bool):
            errors.append(f"{label}: validated must be boolean")
        notes = point.get("notes", [])
        if notes is not None and not isinstance(notes, list):
            errors.append(f"{label}: notes must be a list")
    return errors


__all__ = ["validate_property_data"]
