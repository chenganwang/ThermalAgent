from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .aliases import normalize_fluid, normalize_property_name
from .contracts import PropertyDataPoint
from .validator import validate_property_data


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "reference" / "coolant_properties"


def _resolve_path(data_path: str | Path | None = None) -> Path:
    return Path(data_path) if data_path is not None else DEFAULT_DATA_DIR


def _candidate_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*_properties.json"))
    return []


def _to_point(raw: dict[str, Any]) -> PropertyDataPoint | None:
    fluid = normalize_fluid(str(raw.get("fluid") or ""))
    prop = normalize_property_name(str(raw.get("property_name") or ""))
    if fluid is None or prop is None:
        return None
    notes = raw.get("notes") if isinstance(raw.get("notes"), list) else []
    return PropertyDataPoint(
        fluid=fluid,
        property_name=prop,
        temperature_c=float(raw["temperature_c"]),
        concentration_percent=(
            None if raw.get("concentration_percent") is None else float(raw["concentration_percent"])
        ),
        value=float(raw["value"]),
        unit=str(raw["unit"]),
        source_id=str(raw["source_id"]),
        source_title=str(raw["source_title"]),
        source_type=str(raw["source_type"]),
        source_quality=str(raw["source_quality"]),
        validated=bool(raw["validated"]),
        notes=[str(item) for item in notes],
    )


def load_property_data_points(
    data_path: str | Path | None = None,
    *,
    include_unvalidated: bool = False,
) -> tuple[list[PropertyDataPoint], list[str]]:
    path = _resolve_path(data_path)
    files = _candidate_files(path)
    if not files:
        return [], [f"data_path_missing_or_empty: {path}"]

    points: list[PropertyDataPoint] = []
    errors: list[str] = []
    for file_path in files:
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{file_path}: failed to read JSON: {exc}")
            continue

        validation_errors = validate_property_data(data, source_label=str(file_path))
        if validation_errors:
            errors.extend(validation_errors)
            continue
        for raw in data.get("data_points") or []:
            if raw.get("validated") is False and not include_unvalidated:
                continue
            point = _to_point(raw)
            if point is None:
                errors.append(f"{file_path}: unsupported fluid or property in point: {raw}")
                continue
            points.append(point)
    return points, errors


__all__ = ["DEFAULT_DATA_DIR", "load_property_data_points"]
