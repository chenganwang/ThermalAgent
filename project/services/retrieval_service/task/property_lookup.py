from __future__ import annotations

import re
from typing import Any

from ..properties.aliases import detect_fluid, detect_property_name
from .normalizer import has_any, normalize_query


_THERMAL_ANALOGY_TERMS = (
    "冷板",
    "液冷",
    "冷却液",
    "CDU",
    "TIM",
    "热阻",
    "流道",
    "泵",
    "换热器",
    "芯片",
    "服务器",
    "cold plate",
    "liquid cooling",
    "coolant",
    "thermal resistance",
    "flow channel",
    "pump",
    "heat exchanger",
)

_NON_ENGINEERING_ANALOGY_TERMS = (
    "食堂",
    "排队",
    "奶茶",
    "公交",
    "宿舍",
    "游戏",
    "电影院",
    "超市",
    "楼道",
    "交通",
)

_COOLANT_PROPERTY_CONTEXT_TERMS = (
    "冷却液",
    "冷却水",
    "冷媒",
    "工质",
    "乙二醇",
    "丙二醇",
    "乙二醇水溶液",
    "丙二醇水溶液",
    "glycol",
    "egw",
    "pgw",
    "coolant",
    "water glycol",
    "ethylene glycol water",
    "propylene glycol water",
    "cooling water",
    "air",
    "dry air",
    "空气",
    "干空气",
)

_PROPERTY_LOOKUP_RE = re.compile(
    r"比热容|比热|密度|黏度|粘度|动力黏度|动力粘度|运动黏度|运动粘度|导热系数|热导率|物性|物性参数|"
    r"specific\s+heat|\bcp\b|\bc_p\b|density|viscosity|kinematic\s+viscosity|thermal\s+conductivity|property",
    re.IGNORECASE,
)

_CONCENTRATION_RE = re.compile(
    r"(?:质量分数|体积分数|浓度)\s*\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*(?:wt\s*%|vol\s*%|%)",
    re.IGNORECASE,
)
_TEMPERATURE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:℃|°c|degc|\bc\b|\bk\b)", re.IGNORECASE)
_WATER_CONTEXT_RE = re.compile(
    r"(?<!乙二醇)(?<!丙二醇)(?:冷却水|水的|水在|water|cooling\s+water)",
    re.IGNORECASE,
)

_PROPERTY_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cp", ("cp", "c_p", "比热容", "比热", "specific heat")),
    ("rho", ("rho", "ρ", "密度", "density")),
    ("mu", ("mu", "μ", "黏度", "粘度", "动力黏度", "动力粘度", "viscosity", "dynamic viscosity")),
    ("nu", ("nu", "ν", "运动黏度", "运动粘度", "kinematic viscosity")),
    ("k", ("导热系数", "热导率", "thermal conductivity")),
)


def is_irrelevant_or_analogy_query(query: str) -> bool:
    """Detect mixed thermal-engineering and everyday analogy questions."""

    normalized = normalize_query(query)
    return has_any(normalized, _THERMAL_ANALOGY_TERMS) and has_any(normalized, _NON_ENGINEERING_ANALOGY_TERMS)


def is_property_lookup_query(query: str) -> bool:
    """Detect coolant property table / parameter lookup questions."""

    normalized = normalize_query(query)
    if not normalized:
        return False
    has_property = bool(_PROPERTY_LOOKUP_RE.search(normalized)) or detect_property_name(normalized) is not None
    has_coolant_context = has_any(normalized, _COOLANT_PROPERTY_CONTEXT_TERMS) or bool(
        _WATER_CONTEXT_RE.search(normalized)
    ) or detect_fluid(normalized) is not None
    has_glycol_or_concentration = has_any(normalized, ("乙二醇", "丙二醇", "glycol", "egw", "pgw")) or bool(
        _CONCENTRATION_RE.search(normalized)
    )
    return has_property and (has_coolant_context or has_glycol_or_concentration)


def detect_property_lookup(query: str) -> dict[str, Any]:
    """Detect coolant property table intent without providing values."""

    normalized = normalize_query(query)
    lowered = normalized.lower()
    properties: list[str] = []
    for canonical, aliases in _PROPERTY_ALIASES:
        if any(alias.lower() in lowered for alias in aliases):
            properties.append(canonical)

    signals: list[str] = []
    if has_any(normalized, _COOLANT_PROPERTY_CONTEXT_TERMS) or bool(_WATER_CONTEXT_RE.search(normalized)) or detect_fluid(normalized) is not None:
        signals.append("coolant_context")
    if bool(_CONCENTRATION_RE.search(normalized)):
        signals.append("concentration")
    if bool(_TEMPERATURE_RE.search(normalized)):
        signals.append("temperature")
    if bool(_PROPERTY_LOOKUP_RE.search(normalized)):
        signals.append("property_name")

    return {
        "is_property_lookup": is_property_lookup_query(normalized),
        "properties": properties,
        "signals": signals,
    }
