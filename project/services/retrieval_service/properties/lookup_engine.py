from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain_knowledge.property_schemas import (
    PROPERTY_STATUS_EXACT as DOMAIN_PROPERTY_STATUS_EXACT,
    PROPERTY_STATUS_INTERPOLATED as DOMAIN_PROPERTY_STATUS_INTERPOLATED,
    PROPERTY_STATUS_MISSING_DATA as DOMAIN_PROPERTY_STATUS_MISSING_DATA,
    PROPERTY_STATUS_MISSING_PARAMS as DOMAIN_PROPERTY_STATUS_MISSING_PARAMS,
    PROPERTY_STATUS_UNSUPPORTED_FLUID as DOMAIN_PROPERTY_STATUS_UNSUPPORTED_FLUID,
    PROPERTY_STATUS_UNSUPPORTED_PROPERTY as DOMAIN_PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
    PROPERTY_STATUS_UNSUPPORTED_RANGE as DOMAIN_PROPERTY_STATUS_UNSUPPORTED_RANGE,
)
from ..domain_knowledge.property_store import get_default_property_store, legacy_property_name
from .aliases import normalize_fluid, normalize_property_name
from .contracts import (
    PROPERTY_STATUS_FAILED,
    PROPERTY_STATUS_MISSING_DATA,
    PROPERTY_STATUS_MISSING_PARAMS,
    PROPERTY_STATUS_SUCCESS,
    PROPERTY_STATUS_UNSUPPORTED_FLUID,
    PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
    PROPERTY_STATUS_UNSUPPORTED_RANGE,
    PropertyDataPoint,
    PropertyLookupResult,
    PropertyQuery,
)
from .data_loader import load_property_data_points
from .interpolation import build_temperature_interpolation, linear_interpolate


_SUPPORTED_FLUIDS = {"water", "air", "EGW", "PGW"}
_SUPPORTED_PROPERTIES = {"cp", "density", "viscosity", "kinematic_viscosity", "thermal_conductivity"}


def _domain_result_to_legacy(
    domain_result: Any,
    *,
    query_fluid: str,
    query_property: str,
) -> PropertyLookupResult:
    data = domain_result.to_dict() if hasattr(domain_result, "to_dict") else dict(domain_result or {})
    domain_status = str(data.get("status") or PROPERTY_STATUS_FAILED)
    normalized_property = legacy_property_name(data.get("normalized_property_name"))
    if domain_status in {DOMAIN_PROPERTY_STATUS_EXACT, DOMAIN_PROPERTY_STATUS_INTERPOLATED}:
        status = PROPERTY_STATUS_SUCCESS
    elif domain_status == DOMAIN_PROPERTY_STATUS_MISSING_PARAMS:
        status = PROPERTY_STATUS_MISSING_PARAMS
    elif domain_status == DOMAIN_PROPERTY_STATUS_MISSING_DATA:
        status = PROPERTY_STATUS_MISSING_DATA
    elif domain_status == DOMAIN_PROPERTY_STATUS_UNSUPPORTED_FLUID:
        status = PROPERTY_STATUS_UNSUPPORTED_FLUID
    elif domain_status == DOMAIN_PROPERTY_STATUS_UNSUPPORTED_PROPERTY:
        status = PROPERTY_STATUS_UNSUPPORTED_PROPERTY
    elif domain_status == DOMAIN_PROPERTY_STATUS_UNSUPPORTED_RANGE:
        status = PROPERTY_STATUS_UNSUPPORTED_RANGE
    else:
        status = PROPERTY_STATUS_FAILED

    source = data.get("source")
    if isinstance(source, dict) and "source_name" in source and "source_title" not in source:
        source = dict(source)
        source["source_title"] = source.get("source_name")
    return _base_result(
        status=status,
        fluid=query_fluid,
        normalized_fluid=data.get("normalized_fluid"),
        property_name=query_property,
        normalized_property_name=normalized_property,
        temperature_c=data.get("temperature_c"),
        concentration_percent=data.get("concentration_percent"),
        value=data.get("value"),
        unit=data.get("unit"),
        source=source,
        interpolation=data.get("interpolation"),
        warnings=list(data.get("warnings") or []),
        missing_fields=list(data.get("missing_fields") or []),
        supported_range=data.get("supported_range"),
        error=data.get("error"),
    )


def _lookup_domain_property(
    *,
    fluid_text: str,
    property_text: str,
    temperature: float | None,
    concentration: float | None,
    allow_interpolation: bool,
) -> PropertyLookupResult:
    domain_result = get_default_property_store().lookup(
        fluid_text,
        property_text,
        temperature_c=temperature,
        concentration_percent=concentration,
        allow_interpolation=allow_interpolation,
    )
    return _domain_result_to_legacy(domain_result, query_fluid=fluid_text, query_property=property_text)


def _base_result(
    *,
    status: str,
    fluid: str,
    normalized_fluid: str | None,
    property_name: str,
    normalized_property_name: str | None,
    temperature_c: float | None,
    concentration_percent: float | None,
    value: float | None = None,
    unit: str | None = None,
    source: dict[str, Any] | None = None,
    interpolation: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    missing_fields: list[str] | None = None,
    supported_range: dict[str, Any] | None = None,
    error: str | None = None,
) -> PropertyLookupResult:
    return PropertyLookupResult(
        status=status,
        fluid=fluid,
        normalized_fluid=normalized_fluid or "",
        property_name=property_name,
        normalized_property_name=normalized_property_name or "",
        temperature_c=temperature_c,
        concentration_percent=concentration_percent,
        value=value,
        unit=unit,
        source=source,
        interpolation=interpolation,
        warnings=list(warnings or []),
        missing_fields=list(missing_fields or []),
        supported_range=supported_range,
        error=error,
    )


def _supported_range(points: list[PropertyDataPoint]) -> dict[str, Any] | None:
    if not points:
        return None
    temps = [point.temperature_c for point in points]
    concentrations = sorted({point.concentration_percent for point in points if point.concentration_percent is not None})
    data: dict[str, Any] = {
        "temperature_c": {"min": min(temps), "max": max(temps), "values": sorted(set(temps))},
    }
    if concentrations:
        data["concentration_percent"] = {
            "min": min(concentrations),
            "max": max(concentrations),
            "values": concentrations,
        }
    return data


def _same_concentration(point: PropertyDataPoint, concentration: float | None) -> bool:
    if concentration is None:
        return point.concentration_percent is None
    return point.concentration_percent is not None and abs(point.concentration_percent - concentration) < 1e-9


def _warnings_for_point(point: PropertyDataPoint) -> list[str]:
    warnings = list(point.notes)
    if point.fluid == "water" and point.source_id == "default_water_engineering_assumption":
        if "default_water_assumption" not in warnings:
            warnings.append("default_water_assumption")
    return warnings


def _success_from_point(
    *,
    query_fluid: str,
    normalized_fluid: str,
    query_property: str,
    normalized_property: str,
    point: PropertyDataPoint,
    temperature_c: float,
    concentration_percent: float | None,
) -> PropertyLookupResult:
    return _base_result(
        status=PROPERTY_STATUS_SUCCESS,
        fluid=query_fluid,
        normalized_fluid=normalized_fluid,
        property_name=query_property,
        normalized_property_name=normalized_property,
        temperature_c=temperature_c,
        concentration_percent=concentration_percent,
        value=point.value,
        unit=point.unit,
        source=point.source_dict(),
        warnings=_warnings_for_point(point),
        supported_range=_supported_range([point]),
    )


def _success_from_interpolation(
    *,
    query_fluid: str,
    normalized_fluid: str,
    query_property: str,
    normalized_property: str,
    lower: PropertyDataPoint,
    upper: PropertyDataPoint,
    temperature_c: float,
    concentration_percent: float | None,
) -> PropertyLookupResult:
    value = linear_interpolate(temperature_c, lower.temperature_c, lower.value, upper.temperature_c, upper.value)
    interpolation = build_temperature_interpolation(
        lower=lower,
        upper=upper,
        target_temperature_c=temperature_c,
        value=value,
    )
    warnings = sorted(set(_warnings_for_point(lower) + _warnings_for_point(upper) + ["interpolated_value"]))
    return _base_result(
        status=PROPERTY_STATUS_SUCCESS,
        fluid=query_fluid,
        normalized_fluid=normalized_fluid,
        property_name=query_property,
        normalized_property_name=normalized_property,
        temperature_c=temperature_c,
        concentration_percent=concentration_percent,
        value=value,
        unit=lower.unit,
        source={
            "source_type": "interpolated_from_validated_points",
            "lower_source": lower.source_dict(),
            "upper_source": upper.source_dict(),
        },
        interpolation=interpolation,
        warnings=warnings,
        supported_range=_supported_range([lower, upper]),
    )


def lookup_coolant_property(
    fluid: str | PropertyQuery,
    property_name: str | None = None,
    temperature_c: float | None = None,
    concentration_percent: float | None = None,
    allow_interpolation: bool = True,
    data_path: str | Path | None = None,
) -> PropertyLookupResult:
    try:
        if isinstance(fluid, PropertyQuery):
            query = fluid
            fluid_text = query.fluid
            property_text = query.property_name
            temperature = query.temperature_c
            concentration = query.concentration_percent
            interpolate = query.allow_interpolation
        else:
            fluid_text = str(fluid or "")
            property_text = str(property_name or "")
            temperature = temperature_c
            concentration = concentration_percent
            interpolate = allow_interpolation

        if data_path is None:
            return _lookup_domain_property(
                fluid_text=fluid_text,
                property_text=property_text,
                temperature=temperature,
                concentration=concentration,
                allow_interpolation=interpolate,
            )

        normalized_fluid = normalize_fluid(fluid_text)
        normalized_property = normalize_property_name(property_text)
        if normalized_fluid not in _SUPPORTED_FLUIDS:
            return _base_result(
                status=PROPERTY_STATUS_UNSUPPORTED_FLUID,
                fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                property_name=property_text,
                normalized_property_name=normalized_property,
                temperature_c=temperature,
                concentration_percent=concentration,
                error=f"Unsupported coolant fluid: {fluid_text}",
            )
        if normalized_property not in _SUPPORTED_PROPERTIES:
            return _base_result(
                status=PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
                fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                property_name=property_text,
                normalized_property_name=normalized_property,
                temperature_c=temperature,
                concentration_percent=concentration,
                error=f"Unsupported property: {property_text}",
            )

        missing: list[str] = []
        if temperature is None:
            missing.append("temperature_c")
        if normalized_fluid in {"EGW", "PGW"} and concentration is None:
            missing.append("concentration_percent")
        if missing:
            return _base_result(
                status=PROPERTY_STATUS_MISSING_PARAMS,
                fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                property_name=property_text,
                normalized_property_name=normalized_property,
                temperature_c=temperature,
                concentration_percent=concentration,
                missing_fields=missing,
                error="Missing required property lookup inputs: " + ", ".join(missing),
            )

        temperature_value = float(temperature)
        concentration_value = None if concentration is None else float(concentration)
        if normalized_fluid == "water":
            concentration_value = None

        points, errors = load_property_data_points(data_path)
        if not points:
            return _base_result(
                status=PROPERTY_STATUS_MISSING_DATA,
                fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                property_name=property_text,
                normalized_property_name=normalized_property,
                temperature_c=temperature_value,
                concentration_percent=concentration_value,
                warnings=errors,
                error="No validated coolant property data is available.",
            )

        same_property_points = [
            point
            for point in points
            if point.fluid == normalized_fluid and point.property_name == normalized_property
        ]
        if not same_property_points:
            return _base_result(
                status=PROPERTY_STATUS_MISSING_DATA,
                fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                property_name=property_text,
                normalized_property_name=normalized_property,
                temperature_c=temperature_value,
                concentration_percent=concentration_value,
                warnings=errors,
                error="No validated data for this coolant/property combination.",
            )

        concentration_points = [point for point in same_property_points if _same_concentration(point, concentration_value)]
        if not concentration_points:
            return _base_result(
                status=PROPERTY_STATUS_UNSUPPORTED_RANGE,
                fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                property_name=property_text,
                normalized_property_name=normalized_property,
                temperature_c=temperature_value,
                concentration_percent=concentration_value,
                supported_range=_supported_range(same_property_points),
                error="Requested concentration is outside the available validated data.",
            )

        exact = [point for point in concentration_points if abs(point.temperature_c - temperature_value) < 1e-9]
        if exact:
            return _success_from_point(
                query_fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                query_property=property_text,
                normalized_property=normalized_property,
                point=exact[0],
                temperature_c=temperature_value,
                concentration_percent=concentration_value,
            )

        sorted_points = sorted(concentration_points, key=lambda point: point.temperature_c)
        lower = None
        upper = None
        for point in sorted_points:
            if point.temperature_c < temperature_value:
                lower = point
            elif point.temperature_c > temperature_value and upper is None:
                upper = point
                break

        if interpolate and lower is not None and upper is not None and lower.unit == upper.unit:
            return _success_from_interpolation(
                query_fluid=fluid_text,
                normalized_fluid=normalized_fluid,
                query_property=property_text,
                normalized_property=normalized_property,
                lower=lower,
                upper=upper,
                temperature_c=temperature_value,
                concentration_percent=concentration_value,
            )

        return _base_result(
            status=PROPERTY_STATUS_UNSUPPORTED_RANGE,
            fluid=fluid_text,
            normalized_fluid=normalized_fluid,
            property_name=property_text,
            normalized_property_name=normalized_property,
            temperature_c=temperature_value,
            concentration_percent=concentration_value,
            supported_range=_supported_range(concentration_points),
            error="Requested temperature is outside the available validated data.",
        )
    except Exception as exc:
        return _base_result(
            status=PROPERTY_STATUS_FAILED,
            fluid=str(fluid),
            normalized_fluid=None,
            property_name=str(property_name or ""),
            normalized_property_name=None,
            temperature_c=temperature_c,
            concentration_percent=concentration_percent,
            error=str(exc).strip() or exc.__class__.__name__,
        )


__all__ = ["lookup_coolant_property"]
