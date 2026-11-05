from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PROPERTY_STATUS_EXACT = "exact"
PROPERTY_STATUS_INTERPOLATED = "interpolated"
PROPERTY_STATUS_MISSING_PARAMS = "missing_params"
PROPERTY_STATUS_MISSING_DATA = "missing_data"
PROPERTY_STATUS_UNSUPPORTED_FLUID = "unsupported_fluid"
PROPERTY_STATUS_UNSUPPORTED_PROPERTY = "unsupported_property"
PROPERTY_STATUS_UNSUPPORTED_RANGE = "unsupported_range"
PROPERTY_STATUS_INVALID_DATA = "invalid_data"
PROPERTY_STATUS_FAILED = "failed"

SUPPORTED_STATUSES = {
    PROPERTY_STATUS_EXACT,
    PROPERTY_STATUS_INTERPOLATED,
    PROPERTY_STATUS_MISSING_PARAMS,
    PROPERTY_STATUS_MISSING_DATA,
    PROPERTY_STATUS_UNSUPPORTED_FLUID,
    PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
    PROPERTY_STATUS_UNSUPPORTED_RANGE,
    PROPERTY_STATUS_INVALID_DATA,
    PROPERTY_STATUS_FAILED,
}


@dataclass(frozen=True)
class PropertySource:
    source_id: str
    source_name: str
    source_type: str
    source_status: str
    source_quality: str
    document_id: int | None = None
    document_name: str | None = None
    page: str | int | None = None
    url: str | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PropertySource":
        return cls(
            source_id=str(raw.get("source_id") or ""),
            source_name=str(raw.get("source_name") or raw.get("source_title") or ""),
            source_type=str(raw.get("source_type") or ""),
            source_status=str(raw.get("source_status") or "source_required"),
            source_quality=str(raw.get("source_quality") or ""),
            document_id=_optional_int(raw.get("document_id")),
            document_name=_optional_str(raw.get("document_name")),
            page=raw.get("page"),
            url=_optional_str(raw.get("url")),
            note=_optional_str(raw.get("note")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FluidPropertyPoint:
    fluid: str
    property_name: str
    temperature_c: float
    value: float
    unit: str
    source_id: str
    pressure_condition: str = "unspecified"
    concentration_percent: float | None = None
    source_status: str = "source_required"
    source_quality: str = ""
    validated: bool = False
    notes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FluidPropertyPoint":
        return cls(
            fluid=str(raw.get("fluid") or ""),
            property_name=str(raw.get("property_name") or ""),
            temperature_c=float(raw["temperature_c"]),
            value=float(raw["value"]),
            unit=str(raw.get("unit") or ""),
            source_id=str(raw.get("source_id") or ""),
            pressure_condition=str(raw.get("pressure_condition") or "unspecified"),
            concentration_percent=(
                None if raw.get("concentration_percent") is None else float(raw.get("concentration_percent"))
            ),
            source_status=str(raw.get("source_status") or "source_required"),
            source_quality=str(raw.get("source_quality") or ""),
            validated=bool(raw.get("validated", False)),
            notes=tuple(str(item) for item in raw.get("notes") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FluidPropertyLookupResult:
    status: str
    fluid: str
    normalized_fluid: str
    property_name: str
    normalized_property_name: str
    temperature_c: float | None
    concentration_percent: float | None
    value: float | None
    unit: str | None
    pressure_condition: str | None
    source: dict[str, Any] | None
    interpolation: dict[str, Any] | None
    supported_range: dict[str, Any] | None
    warnings: tuple[str, ...]
    missing_fields: tuple[str, ...]
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "FluidPropertyLookupResult",
    "FluidPropertyPoint",
    "PROPERTY_STATUS_EXACT",
    "PROPERTY_STATUS_FAILED",
    "PROPERTY_STATUS_INTERPOLATED",
    "PROPERTY_STATUS_INVALID_DATA",
    "PROPERTY_STATUS_MISSING_DATA",
    "PROPERTY_STATUS_MISSING_PARAMS",
    "PROPERTY_STATUS_UNSUPPORTED_FLUID",
    "PROPERTY_STATUS_UNSUPPORTED_PROPERTY",
    "PROPERTY_STATUS_UNSUPPORTED_RANGE",
    "PropertySource",
    "SUPPORTED_STATUSES",
]
