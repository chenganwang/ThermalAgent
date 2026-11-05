from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .property_interpolation import build_linear_temperature_interpolation, linear_interpolate
from .property_schemas import (
    FluidPropertyLookupResult,
    FluidPropertyPoint,
    PROPERTY_STATUS_EXACT,
    PROPERTY_STATUS_FAILED,
    PROPERTY_STATUS_INTERPOLATED,
    PROPERTY_STATUS_MISSING_DATA,
    PROPERTY_STATUS_MISSING_PARAMS,
    PROPERTY_STATUS_UNSUPPORTED_FLUID,
    PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
    PROPERTY_STATUS_UNSUPPORTED_RANGE,
    PropertySource,
)


DEFAULT_PROPERTY_DATA = Path(__file__).resolve().parent / "data" / "fluid_properties.json"
DEFAULT_PROPERTY_SOURCES = Path(__file__).resolve().parent / "data" / "fluid_property_sources.json"

SUPPORTED_FLUIDS = {"water", "air", "EGW", "PGW"}
SUPPORTED_PROPERTIES = {
    "specific_heat",
    "density",
    "dynamic_viscosity",
    "kinematic_viscosity",
    "thermal_conductivity",
}

_FLUID_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("water", ("water", "liquid water", "cooling water", "deionized water", "di water", "水", "冷却水", "去离子水")),
    ("air", ("air", "dry air", "空气", "干空气")),
    ("EGW", ("egw", "ethylene glycol water", "ethylene glycol-water", "ethylene glycol/water", "乙二醇水", "乙二醇水溶液", "乙二醇冷却液")),
    ("PGW", ("pgw", "propylene glycol water", "propylene glycol-water", "propylene glycol/water", "丙二醇水", "丙二醇水溶液", "丙二醇冷却液")),
)

_PROPERTY_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("specific_heat", ("specific_heat", "specific heat", "specific heat capacity", "cp", "c_p", "比热", "比热容", "定压比热")),
    ("density", ("density", "rho", "ρ", "密度")),
    ("dynamic_viscosity", ("dynamic_viscosity", "dynamic viscosity", "viscosity", "mu", "μ", "动力黏度", "动力粘度", "黏度", "粘度")),
    ("kinematic_viscosity", ("kinematic_viscosity", "kinematic viscosity", "nu", "ν", "运动黏度", "运动粘度")),
    ("thermal_conductivity", ("thermal_conductivity", "thermal conductivity", "conductivity", "lambda", "λ", "导热系数", "热导率")),
)


def _normalize(text: str | None) -> str:
    value = str(text or "").strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", value)


def _contains_alias(text: str, alias: str) -> bool:
    normalized_alias = alias.lower()
    if re.fullmatch(r"[a-z0-9_]+", normalized_alias):
        return bool(re.search(rf"(?<![a-z0-9_]){re.escape(normalized_alias)}(?![a-z0-9_])", text))
    return normalized_alias in text


def normalize_fluid_name(value: str | None) -> str | None:
    text = _normalize(value)
    if not text:
        return None
    for canonical, aliases in _FLUID_ALIASES:
        if any(_contains_alias(text, alias) for alias in aliases):
            return canonical
    return None


def normalize_property_name(value: str | None) -> str | None:
    text = _normalize(value)
    if not text:
        return None
    if text == "k":
        return "thermal_conductivity"
    for canonical, aliases in _PROPERTY_ALIASES:
        if any(_contains_alias(text, alias) for alias in aliases):
            return canonical
    return None


def legacy_property_name(canonical: str | None) -> str:
    mapping = {
        "specific_heat": "cp",
        "density": "density",
        "dynamic_viscosity": "viscosity",
        "kinematic_viscosity": "kinematic_viscosity",
        "thermal_conductivity": "thermal_conductivity",
    }
    return mapping.get(str(canonical or ""), str(canonical or ""))


class FluidPropertyStore:
    def __init__(
        self,
        data_path: str | Path | None = None,
        sources_path: str | Path | None = None,
    ) -> None:
        self.data_path = Path(data_path) if data_path is not None else DEFAULT_PROPERTY_DATA
        self.sources_path = Path(sources_path) if sources_path is not None else DEFAULT_PROPERTY_SOURCES
        self.sources = self._load_sources(self.sources_path)
        self.points = self._load_points(self.data_path)

    @staticmethod
    def _load_sources(path: Path) -> dict[str, PropertySource]:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_sources = data.get("sources") if isinstance(data, dict) else data
        if not isinstance(raw_sources, list):
            raise ValueError(f"{path}: sources must be a list")
        sources = [PropertySource.from_dict(item) for item in raw_sources]
        return {item.source_id: item for item in sources if item.source_id}

    def _load_points(self, path: Path) -> list[FluidPropertyPoint]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_points = data.get("property_points") if isinstance(data, dict) else data
        if not isinstance(raw_points, list):
            raise ValueError(f"{path}: property_points must be a list")
        points: list[FluidPropertyPoint] = []
        for index, raw in enumerate(raw_points):
            point = FluidPropertyPoint.from_dict(raw)
            fluid = normalize_fluid_name(point.fluid)
            prop = normalize_property_name(point.property_name)
            if fluid not in SUPPORTED_FLUIDS or prop not in SUPPORTED_PROPERTIES:
                raise ValueError(f"{path}: unsupported fluid/property at property_points[{index}]")
            if point.source_id not in self.sources:
                raise ValueError(f"{path}: unknown source_id at property_points[{index}]: {point.source_id}")
            source = self.sources[point.source_id]
            points.append(
                FluidPropertyPoint(
                    fluid=fluid,
                    property_name=prop,
                    temperature_c=point.temperature_c,
                    value=point.value,
                    unit=point.unit,
                    source_id=point.source_id,
                    pressure_condition=point.pressure_condition,
                    concentration_percent=point.concentration_percent,
                    source_status=source.source_status,
                    source_quality=source.source_quality or point.source_quality,
                    validated=point.validated,
                    notes=point.notes,
                )
            )
        return points

    def list_points(self) -> list[FluidPropertyPoint]:
        return list(self.points)

    def lookup(
        self,
        fluid: str,
        property_name: str,
        *,
        temperature_c: float | None,
        concentration_percent: float | None = None,
        allow_interpolation: bool = True,
    ) -> FluidPropertyLookupResult:
        try:
            normalized_fluid = normalize_fluid_name(fluid)
            normalized_property = normalize_property_name(property_name)
            if normalized_fluid not in SUPPORTED_FLUIDS:
                return self._result(
                    status=PROPERTY_STATUS_UNSUPPORTED_FLUID,
                    fluid=fluid,
                    normalized_fluid=normalized_fluid,
                    property_name=property_name,
                    normalized_property_name=normalized_property,
                    temperature_c=temperature_c,
                    concentration_percent=concentration_percent,
                    error=f"Unsupported fluid for local property store: {fluid}",
                )
            if normalized_property not in SUPPORTED_PROPERTIES:
                return self._result(
                    status=PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
                    fluid=fluid,
                    normalized_fluid=normalized_fluid,
                    property_name=property_name,
                    normalized_property_name=normalized_property,
                    temperature_c=temperature_c,
                    concentration_percent=concentration_percent,
                    error=f"Unsupported property for local property store: {property_name}",
                )

            missing: list[str] = []
            if temperature_c is None:
                missing.append("temperature_c")
            if normalized_fluid in {"EGW", "PGW"} and concentration_percent is None:
                missing.append("concentration_percent")
            if missing:
                return self._result(
                    status=PROPERTY_STATUS_MISSING_PARAMS,
                    fluid=fluid,
                    normalized_fluid=normalized_fluid,
                    property_name=property_name,
                    normalized_property_name=normalized_property,
                    temperature_c=temperature_c,
                    concentration_percent=concentration_percent,
                    missing_fields=missing,
                    error="Missing required property lookup inputs: " + ", ".join(missing),
                )

            temperature = float(temperature_c)
            concentration = None if normalized_fluid in {"water", "air"} else float(concentration_percent)
            candidates = [
                point
                for point in self.points
                if point.fluid == normalized_fluid
                and point.property_name == normalized_property
                and self._same_concentration(point.concentration_percent, concentration)
            ]
            all_property_points = [
                point
                for point in self.points
                if point.fluid == normalized_fluid and point.property_name == normalized_property
            ]
            if not all_property_points:
                return self._result(
                    status=PROPERTY_STATUS_MISSING_DATA,
                    fluid=fluid,
                    normalized_fluid=normalized_fluid,
                    property_name=property_name,
                    normalized_property_name=normalized_property,
                    temperature_c=temperature,
                    concentration_percent=concentration,
                    error="No local sourced data for this fluid/property combination.",
                )
            if not candidates:
                return self._result(
                    status=PROPERTY_STATUS_UNSUPPORTED_RANGE,
                    fluid=fluid,
                    normalized_fluid=normalized_fluid,
                    property_name=property_name,
                    normalized_property_name=normalized_property,
                    temperature_c=temperature,
                    concentration_percent=concentration,
                    supported_range=self._supported_range(all_property_points),
                    error="Requested concentration is outside the local sourced data.",
                )

            exact = [point for point in candidates if abs(point.temperature_c - temperature) < 1e-9]
            if exact:
                return self._success(
                    status=PROPERTY_STATUS_EXACT,
                    fluid=fluid,
                    property_name=property_name,
                    point=exact[0],
                    temperature_c=temperature,
                    concentration_percent=concentration,
                )

            sorted_points = sorted(candidates, key=lambda point: point.temperature_c)
            lower = None
            upper = None
            for point in sorted_points:
                if point.temperature_c < temperature:
                    lower = point
                elif point.temperature_c > temperature and upper is None:
                    upper = point
                    break
            if allow_interpolation and lower and upper and lower.unit == upper.unit:
                value = linear_interpolate(temperature, lower.temperature_c, lower.value, upper.temperature_c, upper.value)
                return self._interpolated(
                    fluid=fluid,
                    property_name=property_name,
                    lower=lower,
                    upper=upper,
                    value=value,
                    temperature_c=temperature,
                    concentration_percent=concentration,
                )
            return self._result(
                status=PROPERTY_STATUS_UNSUPPORTED_RANGE,
                fluid=fluid,
                normalized_fluid=normalized_fluid,
                property_name=property_name,
                normalized_property_name=normalized_property,
                temperature_c=temperature,
                concentration_percent=concentration,
                supported_range=self._supported_range(candidates),
                error="Requested temperature is outside the local sourced data. No extrapolation is performed.",
            )
        except Exception as exc:
            return self._result(
                status=PROPERTY_STATUS_FAILED,
                fluid=fluid,
                normalized_fluid=normalize_fluid_name(fluid),
                property_name=property_name,
                normalized_property_name=normalize_property_name(property_name),
                temperature_c=temperature_c,
                concentration_percent=concentration_percent,
                error=str(exc).strip() or exc.__class__.__name__,
            )

    @staticmethod
    def _same_concentration(left: float | None, right: float | None) -> bool:
        if left is None or right is None:
            return left is None and right is None
        return abs(float(left) - float(right)) < 1e-9

    @staticmethod
    def _supported_range(points: list[FluidPropertyPoint]) -> dict[str, Any] | None:
        if not points:
            return None
        temps = sorted({point.temperature_c for point in points})
        data: dict[str, Any] = {"temperature_c": {"min": min(temps), "max": max(temps), "values": temps}}
        concentrations = sorted({point.concentration_percent for point in points if point.concentration_percent is not None})
        if concentrations:
            data["concentration_percent"] = {
                "min": min(concentrations),
                "max": max(concentrations),
                "values": concentrations,
            }
        return data

    def _source_dict(self, point: FluidPropertyPoint) -> dict[str, Any]:
        source = self.sources.get(point.source_id)
        data = source.to_dict() if source else {"source_id": point.source_id}
        data.update(
            {
                "source_id": point.source_id,
                "source_title": data.get("source_name") or data.get("source_title"),
                "source_status": point.source_status,
                "source_quality": point.source_quality,
                "validated": point.validated,
                "notes": list(point.notes),
            }
        )
        return data

    def _warnings_for_point(self, point: FluidPropertyPoint) -> list[str]:
        warnings = list(point.notes)
        if point.source_status != "verified":
            warnings.append(f"source_status_{point.source_status}")
        if point.source_id == "default_water_engineering_assumption" and "default_water_assumption" not in warnings:
            warnings.append("default_water_assumption")
        return sorted(set(warnings))

    def _success(
        self,
        *,
        status: str,
        fluid: str,
        property_name: str,
        point: FluidPropertyPoint,
        temperature_c: float,
        concentration_percent: float | None,
    ) -> FluidPropertyLookupResult:
        return self._result(
            status=status,
            fluid=fluid,
            normalized_fluid=point.fluid,
            property_name=property_name,
            normalized_property_name=point.property_name,
            temperature_c=temperature_c,
            concentration_percent=concentration_percent,
            value=point.value,
            unit=point.unit,
            pressure_condition=point.pressure_condition,
            source=self._source_dict(point),
            warnings=self._warnings_for_point(point),
            supported_range=self._supported_range([point]),
        )

    def _interpolated(
        self,
        *,
        fluid: str,
        property_name: str,
        lower: FluidPropertyPoint,
        upper: FluidPropertyPoint,
        value: float,
        temperature_c: float,
        concentration_percent: float | None,
    ) -> FluidPropertyLookupResult:
        warnings = sorted(set(self._warnings_for_point(lower) + self._warnings_for_point(upper) + ["interpolated_value"]))
        return self._result(
            status=PROPERTY_STATUS_INTERPOLATED,
            fluid=fluid,
            normalized_fluid=lower.fluid,
            property_name=property_name,
            normalized_property_name=lower.property_name,
            temperature_c=temperature_c,
            concentration_percent=concentration_percent,
            value=value,
            unit=lower.unit,
            pressure_condition=lower.pressure_condition,
            source={
                "source_type": "interpolated_from_local_points",
                "lower_source": self._source_dict(lower),
                "upper_source": self._source_dict(upper),
            },
            interpolation=build_linear_temperature_interpolation(
                lower=lower,
                upper=upper,
                target_temperature_c=temperature_c,
                value=value,
            ),
            supported_range=self._supported_range([lower, upper]),
            warnings=warnings,
        )

    @staticmethod
    def _result(
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
        pressure_condition: str | None = None,
        source: dict[str, Any] | None = None,
        interpolation: dict[str, Any] | None = None,
        supported_range: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        missing_fields: list[str] | None = None,
        error: str | None = None,
    ) -> FluidPropertyLookupResult:
        return FluidPropertyLookupResult(
            status=status,
            fluid=fluid,
            normalized_fluid=normalized_fluid or "",
            property_name=property_name,
            normalized_property_name=normalized_property_name or "",
            temperature_c=temperature_c,
            concentration_percent=concentration_percent,
            value=value,
            unit=unit,
            pressure_condition=pressure_condition,
            source=source,
            interpolation=interpolation,
            supported_range=supported_range,
            warnings=tuple(warnings or ()),
            missing_fields=tuple(missing_fields or ()),
            error=error,
        )


@lru_cache(maxsize=1)
def get_default_property_store() -> FluidPropertyStore:
    return FluidPropertyStore()


__all__ = [
    "DEFAULT_PROPERTY_DATA",
    "DEFAULT_PROPERTY_SOURCES",
    "FluidPropertyStore",
    "SUPPORTED_FLUIDS",
    "SUPPORTED_PROPERTIES",
    "get_default_property_store",
    "legacy_property_name",
    "normalize_fluid_name",
    "normalize_property_name",
]
