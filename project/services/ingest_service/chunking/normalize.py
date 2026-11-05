from __future__ import annotations

import re
from typing import Iterable

_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_HYPHEN_BREAK_RE = re.compile(r"([A-Za-z])\s*-\s*\n\s*([A-Za-z])")

_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*℃\b"), r"\1°C"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*°\s*C\b", re.IGNORECASE), r"\1°C"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*KPa\b", re.IGNORECASE), r"\1kPa"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*MPa\b", re.IGNORECASE), r"\1MPa"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*Pa\b", re.IGNORECASE), r"\1Pa"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*kW\b", re.IGNORECASE), r"\1kW"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*MW\b", re.IGNORECASE), r"\1MW"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*W\b", re.IGNORECASE), r"\1W"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*kg\b", re.IGNORECASE), r"\1kg"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*g\b", re.IGNORECASE), r"\1g"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*mm\b", re.IGNORECASE), r"\1mm"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*cm\b", re.IGNORECASE), r"\1cm"),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*m\b", re.IGNORECASE), r"\1m"),
]

_FORMULAISH_RE = re.compile(r"[=+\-*/^]|≤|≥|≈|≡|∑|∫|→|←|Δ|λ|μ|ρ|η|Nu|Re|Pr")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[\).、])\s+")


def normalize_whitespace(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = _WS_RE.sub(" ", s)
    s = _MULTI_NL_RE.sub("\n\n", s)
    return s.strip()


def normalize_units(s: str) -> str:
    t = s or ""
    t = t.replace("％", "%").replace("·", "*")
    t = t.replace("–", "-").replace("—", "-").replace("−", "-")
    t = t.replace("m²", "m2").replace("m³", "m3")
    t = t.replace("W/(m2·K)", "W/m2/K").replace("W/(m2-K)", "W/m2/K").replace("W/(m2*K)", "W/m2/K")
    for pat, repl in _UNIT_PATTERNS:
        t = pat.sub(repl, t)
    return t


def repair_hyphenation(s: str) -> str:
    return _HYPHEN_BREAK_RE.sub(r"\1\2", s or "")


def looks_formulaish(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    return bool(_FORMULAISH_RE.search(t)) and sum(ch.isdigit() for ch in t) + len(_FORMULAISH_RE.findall(t)) >= 2


def looks_list_item(s: str) -> bool:
    return bool(_BULLET_RE.match((s or "").strip()))


def repair_ocr_paragraph_lines(s: str) -> str:
    """Join broken single lines inside a paragraph, but preserve bullets/formulas/headings-ish lines."""
    t = normalize_whitespace(repair_hyphenation(normalize_units(s)))
    if not t or "\n" not in t:
        return t
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    if len(lines) <= 1:
        return t
    out: list[str] = [lines[0]]
    for ln in lines[1:]:
        prev = out[-1]
        if looks_list_item(ln) or looks_formulaish(ln):
            out.append(ln)
            continue
        if prev.endswith(("。", "！", "？", ".", ":", "；", ";")):
            out.append(ln)
            continue
        # likely OCR split inside sentence
        out[-1] = (prev + " " + ln).strip()
    return "\n".join(out)


def normalize_cell_text(s: str) -> str:
    return normalize_whitespace(normalize_units(s or ""))


def compact_values(values: Iterable[str]) -> str:
    parts = [normalize_cell_text(v) for v in values if normalize_cell_text(v)]
    return " | ".join(parts)
