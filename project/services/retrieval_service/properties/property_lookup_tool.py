from __future__ import annotations

import re
from typing import Any

from .aliases import detect_fluid, detect_property_name
from .lookup_engine import lookup_coolant_property


_TEMPERATURE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:℃|°\s*c|degc|deg\s*c|\bc\b)", re.IGNORECASE)
_CONCENTRATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:wt\s*%|vol\s*%|%)", re.IGNORECASE)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_property_lookup_inputs(query: str) -> dict[str, Any]:
    text = str(query or "")
    temperature = None
    concentration = None
    temp_match = _TEMPERATURE_RE.search(text)
    if temp_match:
        temperature = float(temp_match.group(1))
    concentration_match = _CONCENTRATION_RE.search(text)
    if concentration_match:
        concentration = float(concentration_match.group(1))
    return {
        "query": text,
        "fluid": detect_fluid(text),
        "property_name": detect_property_name(text),
        "temperature_c": temperature,
        "concentration_percent": concentration,
        "allow_interpolation": True,
    }


def run_property_lookup_tool(inputs: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    raw_inputs = dict(inputs or {})
    raw_inputs.update(kwargs)
    query = raw_inputs.get("query")
    parsed: dict[str, Any] = {}
    if query:
        parsed = parse_property_lookup_inputs(str(query))
    merged = dict(parsed)
    merged.update({key: value for key, value in raw_inputs.items() if value is not None})
    result = lookup_coolant_property(
        str(merged.get("fluid") or ""),
        str(merged.get("property_name") or ""),
        temperature_c=_number(merged.get("temperature_c")),
        concentration_percent=_number(merged.get("concentration_percent")),
        allow_interpolation=bool(merged.get("allow_interpolation", True)),
        data_path=merged.get("data_path"),
    )
    data = result.to_dict()
    data["tool_name"] = "coolant_property_lookup"
    data["inputs"] = {
        "fluid": merged.get("fluid"),
        "property_name": merged.get("property_name"),
        "temperature_c": _number(merged.get("temperature_c")),
        "concentration_percent": _number(merged.get("concentration_percent")),
        "allow_interpolation": bool(merged.get("allow_interpolation", True)),
    }
    return data


__all__ = ["parse_property_lookup_inputs", "run_property_lookup_tool"]
