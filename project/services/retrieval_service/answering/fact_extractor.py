from __future__ import annotations

import re
from typing import Any, Sequence

from ..domain_rules import ashrae_rules
from ..schemas import FactExtractionResult

try:
    from services.ingest_service.chunking.pack import strip_packed_meta
except Exception:  # pragma: no cover - defensive fallback for partial installs
    def strip_packed_meta(text: str) -> str:
        return text or ""


def combined_hit_text(hits: Sequence[Any]) -> str:
    parts: list[str] = []
    for hit in hits:
        parts.append(str(getattr(hit, "text", "") or ""))
        parts.append(str(getattr(hit, "expanded_text", "") or ""))
        for neighbor in getattr(hit, "neighbors", []) or []:
            if isinstance(neighbor, dict):
                parts.append(str(neighbor.get("text") or ""))
    return re.sub(r"\s+", " ", strip_packed_meta("\n".join(parts))).strip()


_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_CELSIUS = r"\s*(?:°\s*C\b|℃|C\b|degrees?\s+Celsius\b)"
_RANGE = rf"({_NUMBER})(?:{_CELSIUS})?\s*(?:to|[-–—]|到|至)\s*({_NUMBER}){_CELSIUS}"
_CLASS = re.compile(r"\b(?:H1|A[1-4]|W(?:17|27|32|40|45))\b|\bW\+", re.I)


def _class_segments(text: str, klass: str) -> list[str]:
    markers = list(_CLASS.finditer(text))
    return [text[match.end(): markers[index+1].start() if index+1 < len(markers) else min(len(text), match.end()+240)]
            for index, match in enumerate(markers) if match.group().upper() == klass]


def _one_observed(values: list[str]) -> str | None:
    # Contradictory cells require review, not selection of a familiar constant.
    unique = set(values)
    return next(iter(unique)) if len(unique) == 1 else None


def _observed_range(text: str, klass: str, role: str) -> str | None:
    label = r"(?:recommended|推荐)" if role == 'recommended' else r"(?:allowable|允许)"
    pattern = rf"{label}(?:(?!recommended|allowable|推荐|允许).){{0,80}}?{_RANGE}"
    values = []
    for segment in _class_segments(text, klass):
        for match in re.finditer(pattern, segment, re.I):
            values.append(f'{match.group(1)} to {match.group(2)}°C')
    return _one_observed(values)


def _result(fact_type: str, facts: dict[str, str]) -> FactExtractionResult:
    return (FactExtractionResult(has_facts=True, fact_type=fact_type, facts=facts, confidence=.9)
            if facts else FactExtractionResult())


def extract_facts(query: str, hits: Sequence[Any], sources: Sequence[dict[str, Any]] | None = None) -> FactExtractionResult:
    """Extract deterministic table facts from retrieved chunks.

    This layer intentionally handles only source-backed facts. It does not
    estimate or calculate engineering values.
    """

    if not hits:
        return FactExtractionResult()

    text = combined_hit_text(hits)
    if not ashrae_rules.is_ashrae_context(text, sources):
        return FactExtractionResult()

    kind = ashrae_rules.query_kind(query)
    if kind == "cold_plate_formula_absent":
        return FactExtractionResult(
            has_facts=True,
            fact_type="ashrae_cold_plate_formula_absent",
            facts={
                "document_scope": "ASHRAE thermal guidelines / refcard",
                "answer": "not_provided",
                "reason": "The retrieved ASHRAE refcard content covers environmental classes and temperature/humidity limits, not cold-plate internal channel design formulas.",
            },
            confidence=0.82,
        )

    if kind == "w_classes":
        facts = {}
        for klass in ashrae_rules.W_CLASSES:
            values = []
            for segment in _class_segments(text, klass):
                # Stay within this table cell/sentence; a later minimum must
                # never become the class's upper limit.
                cell = re.split(r'[;。\n]|minimum water temperature|lower temperature limit|最低供水温度', segment, maxsplit=1, flags=re.I)[0]
                match = re.match(rf'\s*[:=|]?\s*(?:(?:maximum|upper temperature limit|facility water supply temperature|up to)\s*[:=]?\s*)?(>|greater than)?\s*({_NUMBER}){_CELSIUS}', cell, re.I)
                if match:
                    values.append(('>' if match.group(1) else '') + match.group(2) + '°C')
            value = _one_observed(values)
            if value is not None:
                facts[klass] = value
        minimums = [match.group(1)+'°C' for match in re.finditer(
            rf'(?:minimum water temperature|lower temperature limit|最低供水温度)[^;。]{{0,40}}?({_NUMBER}){_CELSIUS}', text, re.I)]
        minimum = _one_observed(minimums)
        if minimum is not None:
            facts['minimum_water_temperature_all_classes'] = minimum
        return _result('ashrae_w_class_supply_temperature', facts)

    if kind == "h1":
        facts = {role: value for role in ('recommended', 'allowable')
                 if (value := _observed_range(text, 'H1', role)) is not None}
        return _result('ashrae_h1_dry_bulb_temperature', facts)

    if kind == "a1_a4_allowable":
        facts = {klass: value for klass in ashrae_rules.A_CLASSES
                 if (value := _observed_range(text, klass, 'allowable')) is not None}
        return _result('ashrae_a1_a4_allowable_dry_bulb', facts)

    if kind == "a1_a4_recommended":
        # Only an explicit A1-to-A4 grouping can support a shared value.
        pattern = (rf'A1\s*(?:to|through|[-–—]|到|至)\s*A4'
                   rf'(?:(?!\bH1\b|\bA[1-4]\b|allowable|允许).){{0,60}}?'
                   rf'(?:recommended|推荐)(?:(?!\bH1\b|\bA[1-4]\b|allowable|允许).){{0,60}}?{_RANGE}')
        value = _one_observed([f'{match.group(1)} to {match.group(2)}°C' for match in re.finditer(pattern, text, re.I)])
        return _result('ashrae_a1_a4_recommended_dry_bulb',
                       {'A1_to_A4_recommended': value} if value is not None else {})

    return FactExtractionResult()
