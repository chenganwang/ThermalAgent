from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable

from .contracts import truncate_preview

_WS_RE = re.compile(r"\s+")

TERM_ALIASES: dict[str, list[str]] = {
    "cdu": ["cdu", "cooling distribution unit", "冷却分配单元"],
    "rpu": ["rpu", "reservoir and pumping unit", "储液泵单元"],
    "tcs": ["tcs", "technology cooling system", "技术冷却系统"],
    "cold_plate": ["cold plate", "coldplate", "冷板", "水冷板"],
    "direct_liquid_cooling": ["direct liquid cooling", "直接液冷"],
    "immersion_cooling": ["immersion cooling", "浸没式液冷", "浸没液冷"],
    "manifold": ["manifold", "歧管", "分液器"],
    "rack_manifold": ["rack manifold", "机架歧管", "机柜歧管"],
    "facility_water": ["facility water", "设施水", "一次侧水"],
    "chip": ["chip", "processor", "芯片", "处理器"],
    "cpu": ["cpu"],
    "gpu": ["gpu"],
    "tim": ["tim", "thermal interface material", "导热界面材料"],
    "coolant": ["coolant", "cooling fluid", "冷却液", "冷却工质"],
    "pump": ["pump", "泵"],
    "hose": ["hose", "软管"],
    "connector": ["connector", "接头", "连接器"],
    "heat_exchanger": ["heat exchanger", "换热器", "热交换器"],
    "it_loop": ["it loop", "secondary loop", "it侧回路", "二次侧回路"],
    "facility_loop": ["facility loop", "primary loop", "设施侧回路", "一次侧回路"],
}

ALIAS_TO_CANONICAL: dict[str, str] = {
    alias.lower(): canonical
    for canonical, aliases in TERM_ALIASES.items()
    for alias in aliases
}

DISPLAY_NAMES: dict[str, str] = {
    "cdu": "CDU",
    "rpu": "RPU",
    "tcs": "TCS",
    "cold_plate": "cold plate",
    "direct_liquid_cooling": "direct liquid cooling",
    "immersion_cooling": "immersion cooling",
    "manifold": "manifold",
    "rack_manifold": "rack manifold",
    "facility_water": "facility water",
    "chip": "chip",
    "cpu": "CPU",
    "gpu": "GPU",
    "tim": "TIM",
    "coolant": "coolant",
    "pump": "pump",
    "hose": "hose",
    "connector": "connector",
    "heat_exchanger": "heat exchanger",
    "it_loop": "IT loop",
    "facility_loop": "facility loop",
}


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("％", "%").replace("℃", "°C")
    value = value.replace("–", "-").replace("—", "-").replace("−", "-")
    value = value.replace("→", " -> ").replace("➔", " -> ").replace("➡", " -> ")
    value = value.replace("⇒", " -> ").replace("->", " -> ")
    value = value.replace("Δt", "ΔT").replace("delta T", "ΔT").replace("Delta T", "ΔT")
    value = value.replace("m dot", "m_dot").replace("m-dot", "m_dot").replace("ṁ", "m_dot")
    value = value.replace("ρ", "rho").replace("μ", "mu").replace("θ", "theta")
    value = value.replace("²", "2").replace("³", "3")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def compact_text(text: str) -> str:
    return _WS_RE.sub(" ", normalize_text(text)).strip()


def contains_alias(text: str, aliases: Iterable[str]) -> bool:
    lower = compact_text(text).lower()
    for alias in aliases:
        a = alias.lower()
        if re.search(rf"(?<![a-z0-9_]){re.escape(a)}(?![a-z0-9_])", lower):
            return True
    return False


def canonicalize_term(text: str) -> str:
    value = compact_text(text).lower()
    if value in ALIAS_TO_CANONICAL:
        return ALIAS_TO_CANONICAL[value]
    for alias, canonical in sorted(ALIAS_TO_CANONICAL.items(), key=lambda item: len(item[0]), reverse=True):
        if alias and alias in value:
            return canonical
    return slugify(value)


def display_name(canonical: str) -> str:
    return DISPLAY_NAMES.get(canonical, canonical.replace("_", " "))


def slugify(value: str, *, fallback_prefix: str = "item") -> str:
    text = compact_text(value).lower()
    replacements = {
        "°c": "c",
        "Δt": "delta_t",
        "ΔT": "delta_t",
        "%": " percent ",
        "/": " ",
        "*": " ",
        "+": " ",
        "=": " ",
        "(": " ",
        ")": " ",
        ",": " ",
        ";": " ",
        ":": " ",
        "冷板": "cold_plate",
        "芯片": "chip",
        "冷却液": "coolant",
        "堵塞": "blockage",
        "泄漏": "leakage",
        "流量不足": "insufficient_flow",
        "温升": "temperature_rise",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if text:
        return text[:120]
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:12]
    return f"{fallback_prefix}_{digest}"


def make_dedup_key(unit_type: str, *parts: str) -> str:
    clean = [slugify(p, fallback_prefix="part") for p in parts if str(p or "").strip()]
    return f"{unit_type}:{':'.join(clean) if clean else 'unknown'}"


def sentence_windows(text: str, max_len: int = 260) -> list[str]:
    normalized = compact_text(text)
    if not normalized:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?；;])\s+|\n+", normalized) if p.strip()]
    if not parts:
        parts = [normalized]
    windows: list[str] = []
    for part in parts:
        if len(part) <= max_len:
            windows.append(part)
        else:
            windows.append(part[:max_len].rstrip())
    return windows


def source_preview(text: str) -> str:
    return truncate_preview(compact_text(text))
