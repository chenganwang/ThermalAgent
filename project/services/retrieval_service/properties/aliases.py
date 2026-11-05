from __future__ import annotations

import re


_FLUID_ALIASES: dict[str, tuple[str, ...]] = {
    "water": (
        "water",
        "水",
        "冷却水",
        "去离子水",
        "液态水",
        "di water",
        "deionized water",
    ),
    "air": (
        "air",
        "dry air",
        "空气",
        "干空气",
    ),
    "EGW": (
        "egw",
        "ethylene glycol water",
        "ethylene glycol-water",
        "ethylene glycol/water",
        "乙二醇水溶液",
        "乙二醇冷却液",
        "乙二醇水",
        "ethylene glycol",
    ),
    "PGW": (
        "pgw",
        "propylene glycol water",
        "propylene glycol-water",
        "propylene glycol/water",
        "丙二醇水溶液",
        "丙二醇冷却液",
        "丙二醇水",
        "propylene glycol",
    ),
}

_PROPERTY_ALIASES: dict[str, tuple[str, ...]] = {
    "cp": (
        "cp",
        "c_p",
        "specific heat",
        "specific heat capacity",
        "比热",
        "比热容",
        "定压比热",
    ),
    "density": (
        "density",
        "rho",
        "ρ",
        "密度",
    ),
    "viscosity": (
        "viscosity",
        "dynamic viscosity",
        "mu",
        "μ",
        "黏度",
        "粘度",
        "动力黏度",
        "动力粘度",
    ),
    "kinematic_viscosity": (
        "kinematic viscosity",
        "nu",
        "ν",
        "运动黏度",
        "运动粘度",
    ),
    "thermal_conductivity": (
        "thermal conductivity",
        "conductivity",
        "lambda",
        "λ",
        "导热系数",
        "热导率",
    ),
}


def _normalize_text(text: str | None) -> str:
    return str(text or "").strip().lower()


def _contains_alias(text: str, alias: str) -> bool:
    lowered_alias = alias.lower()
    if re.fullmatch(r"[a-z0-9_]+", lowered_alias):
        return bool(re.search(rf"(?<![a-z0-9_]){re.escape(lowered_alias)}(?![a-z0-9_])", text))
    return lowered_alias in text


def normalize_fluid(value: str | None) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    # Match specific mixtures before their water substring. Otherwise e.g.
    # "ethylene glycol water" silently selects pure-water properties.
    for canonical in ("EGW", "PGW", "water", "air"):
        aliases = _FLUID_ALIASES[canonical]
        if any(_contains_alias(text, alias) for alias in aliases):
            return canonical
    if "glycol water" in text and "ethylene" in text:
        return "EGW"
    if "glycol water" in text and "propylene" in text:
        return "PGW"
    return None


def normalize_property_name(value: str | None) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    for canonical, aliases in _PROPERTY_ALIASES.items():
        if any(_contains_alias(text, alias) for alias in aliases):
            return canonical
    if text == "k":
        return "thermal_conductivity"
    return None


def detect_fluid(text: str | None) -> str | None:
    return normalize_fluid(text)


def detect_property_name(text: str | None) -> str | None:
    return normalize_property_name(text)


__all__ = [
    "detect_fluid",
    "detect_property_name",
    "normalize_fluid",
    "normalize_property_name",
]
