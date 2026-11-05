from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from .thermal_terms import dedupe


A_CLASSES = ("A1", "A2", "A3", "A4")
W_CLASSES = ("W17", "W27", "W32", "W40", "W45", "W+")

ASHRAE_QUERY_RE = re.compile(
    r"\b(?:ASHRAE|A1|A2|A3|A4|H1|W17|W27|W32|W40|W45|W\+)\b|"
    r"dry[- ]?bulb|facility water supply|"
    r"干球温度|供水温度|液冷等级|高密度服务器",
    re.IGNORECASE,
)

A1_TO_A4_RE = re.compile(r"A1\s*(?:到|至|-|to|through)\s*A4", re.IGNORECASE)
W_CLASS_RE = re.compile(r"\bW17\b|\bW27\b|\bW32\b|\bW40\b|\bW45\b|\bW\+\b", re.IGNORECASE)
RANGE_SEPARATOR_RE = r"(?:to|-|–|—|到|至)"

ASHRAE_FACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"A1\s*(?:to|through|-|–|—|到|至)\s*A4.{{0,80}}18\s*{RANGE_SEPARATOR_RE}\s*27", re.IGNORECASE),
    re.compile(rf"18\s*{RANGE_SEPARATOR_RE}\s*27.{{0,80}}A1\s*(?:to|through|-|–|—|到|至)\s*A4", re.IGNORECASE),
    re.compile(rf"A1.{{0,50}}15\s*{RANGE_SEPARATOR_RE}\s*32", re.IGNORECASE),
    re.compile(rf"A2.{{0,50}}10\s*{RANGE_SEPARATOR_RE}\s*35", re.IGNORECASE),
    re.compile(rf"A3.{{0,50}}5\s*{RANGE_SEPARATOR_RE}\s*40", re.IGNORECASE),
    re.compile(rf"A4.{{0,50}}5\s*{RANGE_SEPARATOR_RE}\s*45", re.IGNORECASE),
    re.compile(rf"H1.{{0,80}}18\s*{RANGE_SEPARATOR_RE}\s*22", re.IGNORECASE),
    re.compile(rf"H1.{{0,120}}15\s*{RANGE_SEPARATOR_RE}\s*25", re.IGNORECASE),
    re.compile(r"W17.{0,35}17.{0,80}W27.{0,35}27.{0,80}W32.{0,35}32", re.IGNORECASE),
    re.compile(r"W40.{0,35}40.{0,80}W45.{0,35}45.{0,80}W\+.{0,45}(?:>|greater than)\s*45", re.IGNORECASE),
)

LOOKUP_RANGE_PATTERNS: tuple[str, ...] = (
    r"(推荐|允许|规定|给出|对应|供水|干球|湿度|露点).*(温度|范围|等级|是多少)",
    r"(温度|范围|等级).*(推荐|允许|规定|对应|是多少)",
    r"\b(?:A1|A2|A3|A4|H1|W17|W27|W32|W40|W45|W\+)\b.*(?:是多少|range|recommended|allowable)",
    r"(recommended|allowable|dry[- ]?bulb|facility water supply|dew point|humidity).*(range|temperature|class)",
)


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def is_ashrae_query(query: str, entities: Sequence[str] | None = None) -> bool:
    if any(str(entity).upper() == "ASHRAE" for entity in entities or []):
        return True
    return bool(ASHRAE_QUERY_RE.search(query or ""))


def has_a1_to_a4(query: str, entities: Sequence[str] | None = None) -> bool:
    values = {str(item).upper() for item in entities or []}
    q = query or ""
    return all(item in values for item in A_CLASSES) or bool(A1_TO_A4_RE.search(q)) or all(
        re.search(rf"\b{item}\b", q, re.IGNORECASE) for item in A_CLASSES
    )


def has_w_classes(query: str, entities: Sequence[str] | None = None) -> bool:
    values = {str(item).upper() for item in entities or []}
    return any(item in values for item in W_CLASSES) or bool(W_CLASS_RE.search(query or "")) or "液冷等级" in (query or "")


def has_h1(query: str, entities: Sequence[str] | None = None) -> bool:
    values = {str(item).upper() for item in entities or []}
    return "H1" in values or bool(re.search(r"\bH1\b|高密度服务器|high-density", query or "", re.IGNORECASE))


def append_entities(query: str, entities: Sequence[str] | None = None) -> list[str]:
    q = query or ""
    out = [str(item) for item in entities or [] if item]
    if is_ashrae_query(q, out):
        out.append("ASHRAE")
    if has_a1_to_a4(q, out):
        out.extend(["A1", "A2", "A3", "A4", "干球温度"])
    if has_h1(q, out):
        out.extend(["ASHRAE", "H1", "高密度服务器", "干球温度"])
    if has_w_classes(q, out):
        out.extend(["ASHRAE", "液冷等级", "供水温度"])
    if "干球" in q or re.search(r"dry[- ]?bulb", q, re.IGNORECASE):
        out.append("干球温度")
    if "推荐" in q or re.search(r"recommended", q, re.IGNORECASE):
        out.append("推荐")
    if "允许" in q or re.search(r"allowable", q, re.IGNORECASE):
        out.append("允许")
    if "供水" in q or re.search(r"facility water supply|water supply", q, re.IGNORECASE):
        out.append("供水温度")
    return dedupe(out, max_items=32)


def is_lookup_range_query(query: str) -> bool:
    q = normalize_spaces(query)
    return any(re.search(pattern, q, re.IGNORECASE) for pattern in LOOKUP_RANGE_PATTERNS)


def is_calculation_exempt_lookup(query: str) -> bool:
    q = query or ""
    if not is_lookup_range_query(q):
        return False
    return not bool(re.search(r"(已知|given).*(求|计算|估算|calculate|estimate)", q, re.IGNORECASE))


def ashrae_expanded_queries(query: str, entities: Sequence[str] | None = None) -> list[str]:
    q = normalize_spaces(query)
    values = append_entities(q, entities)
    expanded: list[str] = []
    wants_recommended = "推荐" in values or bool(re.search(r"recommended|dry[- ]?bulb|干球", q, re.IGNORECASE))
    wants_allowable = "允许" in values or bool(re.search(r"allowable", q, re.IGNORECASE))

    if has_a1_to_a4(q, values) and wants_recommended:
        expanded.extend(
            [
                "ASHRAE A1 A2 A3 A4 recommended dry-bulb temperature range",
                "A1 to A4 18 to 27 dry-bulb temperature recommended",
                "Table 2.1 Thermal Guidelines for Air Cooling recommended A1 to A4",
                "ASHRAE A1到A4 推荐 干球温度 范围",
            ]
        )
    if has_a1_to_a4(q, values) and wants_allowable:
        expanded.extend(
            [
                "ASHRAE A1 A2 A3 A4 allowable dry-bulb temperature range",
                "A1 15 to 32 A2 10 to 35 A3 5 to 40 A4 5 to 45 allowable dry-bulb temperature",
                "Table 2.1 Thermal Guidelines for Air Cooling allowable A1 A2 A3 A4",
            ]
        )
    if has_h1(q, values):
        expanded.extend(
            [
                "ASHRAE H1 high-density servers recommended allowable dry-bulb temperature",
                "H1 high-density server 18 to 22 recommended 15 to 25 allowable",
                "Table 2.2 Thermal Guidelines for High-Density Servers H1",
            ]
        )
    if has_w_classes(q, values):
        expanded.extend(
            [
                "ASHRAE liquid cooling class W17 W27 W32 W40 W45 W+ facility water supply temperature",
                "W17 17 W27 27 W32 32 W40 40 W45 45 W+ greater than 45 water supply temperature",
                "Table 3.1 Liquid Cooling facility water supply temperature W17 W27 W32 W40 W45 W+ minimum water temperature",
                "ASHRAE 液冷 W17 W27 W32 W40 W45 W+ 供水温度",
            ]
        )
    if not expanded:
        expanded.append(f"ASHRAE {q} thermal guidelines")
    return dedupe(expanded, max_items=8)


def query_kind(query: str, entities: Sequence[str] | None = None) -> str | None:
    q = query or ""
    values = append_entities(q, entities)
    if asks_cold_plate_formula(q):
        return "cold_plate_formula_absent"
    if has_w_classes(q, values):
        return "w_classes"
    if has_h1(q, values):
        return "h1"
    if has_a1_to_a4(q, values) and ("允许" in values or re.search(r"allowable", q, re.IGNORECASE)):
        return "a1_a4_allowable"
    if has_a1_to_a4(q, values):
        return "a1_a4_recommended"
    return None


def asks_cold_plate_formula(query: str) -> bool:
    return bool(
        re.search(
            r"(冷板|cold plate).*(流道|channel).*(公式|formula)|"
            r"(公式|formula).*(冷板|cold plate).*(流道|channel)",
            query or "",
            re.IGNORECASE,
        )
    )


def is_ashrae_context(text: str, sources: Sequence[dict[str, Any]] | None = None) -> bool:
    source_text = " ".join(
        str(src.get("title") or src.get("book_title") or src.get("text_preview") or "") for src in sources or []
    )
    blob = f"{text or ''} {source_text}"
    return bool(
        re.search(
            r"ASHRAE|Thermal Guidelines|A1|A2|A3|A4|H1|W17|W27|W32|W40|W45|W\+|dry[- ]?bulb|facility water supply|液冷等级|供水温度",
            blob,
            re.IGNORECASE,
        )
    )


def ashrae_table_fact_bonus(query: str, text: str, chunk_type: str = "text") -> float:
    """Boost ASHRAE table chunks and demote note-only chunks for range lookups."""

    if not is_ashrae_query(query):
        return 0.0
    blob = normalize_spaces(text)
    if not blob:
        return 0.0
    lower_blob = blob.lower()
    kind = query_kind(query)
    pattern_hits = sum(1 for pattern in ASHRAE_FACT_PATTERNS if pattern.search(blob))

    bonus = 0.0
    if chunk_type in {"table", "table_summary"}:
        bonus += 0.12

    if kind == "w_classes":
        if "table 3.1" in lower_blob:
            bonus += 0.55
        if "liquid cooling" in lower_blob or "facility water supply" in lower_blob:
            bonus += 0.32
        if re.search(r"\bW17\b.*\bW27\b.*\bW32\b.*\bW40\b.*\bW45\b.*W\+", blob, re.IGNORECASE):
            bonus += 0.42
        if "minimum water temperature" in lower_blob:
            bonus += 0.18
        if ("table 2.1" in lower_blob or "air cooling" in lower_blob) and "liquid cooling" not in lower_blob:
            bonus -= 0.38

    elif kind == "h1":
        if "table 2.2" in lower_blob:
            bonus += 0.50
        if "high-density" in lower_blob or re.search(r"\bH1\b", blob):
            bonus += 0.32
        if re.search(rf"H1.{{0,100}}18\s*{RANGE_SEPARATOR_RE}\s*22", blob, re.IGNORECASE):
            bonus += 0.20
        if re.search(rf"H1.{{0,130}}15\s*{RANGE_SEPARATOR_RE}\s*25", blob, re.IGNORECASE):
            bonus += 0.20
        if "table 2.1" in lower_blob and "high-density" not in lower_blob and not re.search(r"\bH1\b", blob):
            bonus -= 0.25

    elif kind in {"a1_a4_recommended", "a1_a4_allowable"}:
        if "table 2.1" in lower_blob or "thermal guidelines for air cooling" in lower_blob:
            bonus += 0.38
        if re.search(r"\bA1\b.*\bA2\b.*\bA3\b.*\bA4\b", blob, re.IGNORECASE):
            bonus += 0.18
        if re.search(rf"18\s*{RANGE_SEPARATOR_RE}\s*27", blob):
            bonus += 0.16

    else:
        if "table 2.1" in lower_blob or "table 2.2" in lower_blob or "table 3.1" in lower_blob:
            bonus += 0.20

    bonus += min(0.90, pattern_hits * 0.18)

    looks_like_notes = "note" in lower_blob or "rate of change" in lower_blob
    if looks_like_notes and pattern_hits == 0:
        bonus -= 0.30
    elif looks_like_notes:
        bonus -= 0.08
    return bonus
