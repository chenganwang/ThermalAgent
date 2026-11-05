from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PROPERTY_STATUS_SUCCESS = "success"
PROPERTY_STATUS_MISSING_PARAMS = "missing_params"
PROPERTY_STATUS_MISSING_DATA = "missing_data"
PROPERTY_STATUS_UNSUPPORTED_FLUID = "unsupported_fluid"
PROPERTY_STATUS_UNSUPPORTED_PROPERTY = "unsupported_property"
PROPERTY_STATUS_UNSUPPORTED_RANGE = "unsupported_range"
PROPERTY_STATUS_INVALID_DATA = "invalid_data"
PROPERTY_STATUS_FAILED = "failed"

PROPERTY_LOOKUP_STATUSES = {
    PROPERTY_STATUS_SUCCESS,
    PROPERTY_STATUS_MISSING_PARAMS,
    PROPERTY_STATUS_MISSING_DATA,
    PROPERTY_STATUS_UNSUPPORTED_FLUID,
    PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
    PROPERTY_STATUS_UNSUPPORTED_RANGE,
    PROPERTY_STATUS_INVALID_DATA,
    PROPERTY_STATUS_FAILED,
}


@dataclass(frozen=True)
class PropertyQuery:
    fluid: str
    property_name: str
    temperature_c: float | None = None
    concentration_percent: float | None = None
    pressure_kpa: float | None = None
    allow_interpolation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyDataPoint:
    fluid: str
    property_name: str
    temperature_c: float
    concentration_percent: float | None
    value: float
    unit: str
    source_id: str
    source_title: str
    source_type: str
    source_quality: str
    validated: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def source_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_title": self.source_title,
            "source_type": self.source_type,
            "source_quality": self.source_quality,
            "validated": self.validated,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class PropertyLookupResult:
    status: str
    fluid: str
    normalized_fluid: str
    property_name: str
    normalized_property_name: str
    temperature_c: float | None
    concentration_percent: float | None
    value: float | None
    unit: str | None
    source: dict[str, Any] | None
    interpolation: dict[str, Any] | None
    warnings: list[str]
    missing_fields: list[str]
    supported_range: dict[str, Any] | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "PROPERTY_LOOKUP_STATUSES",
    "PROPERTY_STATUS_FAILED",
    "PROPERTY_STATUS_INVALID_DATA",
    "PROPERTY_STATUS_MISSING_DATA",
    "PROPERTY_STATUS_MISSING_PARAMS",
    "PROPERTY_STATUS_SUCCESS",
    "PROPERTY_STATUS_UNSUPPORTED_FLUID",
    "PROPERTY_STATUS_UNSUPPORTED_PROPERTY",
    "PROPERTY_STATUS_UNSUPPORTED_RANGE",
    "PropertyDataPoint",
    "PropertyLookupResult",
    "PropertyQuery",
]
