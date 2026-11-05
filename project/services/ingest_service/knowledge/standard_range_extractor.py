from __future__ import annotations

import re

from .atomic import split_sentences
from .contracts import KnowledgeUnitCandidate
from .normalizer import compact_text, make_dedup_key, sentence_windows, slugify

STANDARD_CLASS_RE = re.compile(r"\b(?:ASHRAE|OCP|W17|W27|W32|W40|W45|W\+|A[1-4])\b", re.I)
TEMPERATURE_RANGE_RE = re.compile(
    r"(?:between\s*)?(-?\d+(?:\.\d+)?)\s*(?:°C|℃|C|K)?\s*(?:to|-|~|–|—|and)\s*"
    r"(-?\d+(?:\.\d+)?)\s*(°C|℃|C|K)\b",
    re.I,
)
COOLING_CAPABILITY_RE = re.compile(
    r"\b(?:can\s+support|supports?|support\s+up\s+to|up\s+to|capacity|capability)\b.*?"
    r"(\d+(?:\.\d+)?)\s*(W|kW)\b(?:\s*(?:per|/)\s*([A-Za-z0-9-]+))?",
    re.I,
)
PARAMETER_HINT_RE = re.compile(
    r"supply water|supply temperature|water cooling class|water temperature|recommended|allowable|dry-bulb|"
    r"供水|水温|推荐|允许|范围",
    re.I,
)


def _sentences(text: str) -> list[str]:
    normalized = compact_text(text)
    out: list[str] = []
    for sentence in split_sentences(normalized) + sentence_windows(normalized):
        for part in re.split(r"(?<=[A-Za-z0-9\)])\.\s+(?=[A-Z])", sentence):
            item = part.strip(" 。.;；")
            if item and item not in out:
                out.append(item)
    return out


def _class_tokens(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).upper() for match in STANDARD_CLASS_RE.finditer(text)))


def _canonical_for(sentence: str, property_type: str) -> str:
    tokens = _class_tokens(sentence)
    prefix = "standard_range" if property_type == "standard_range" else "cooling_capability"
    if tokens:
        return f"{tokens[0].lower()}_{prefix}"
    if "ashrae" in sentence.lower():
        return f"ashrae_{prefix}"
    if "ocp" in sentence.lower():
        return f"ocp_{prefix}"
    return prefix


def _range_candidate(sentence: str, source: dict) -> KnowledgeUnitCandidate | None:
    match = TEMPERATURE_RANGE_RE.search(sentence)
    if not match or not STANDARD_CLASS_RE.search(sentence):
        return None
    if not PARAMETER_HINT_RE.search(sentence):
        return None
    low, high, unit = match.groups()
    canonical_name = _canonical_for(sentence, "standard_range")
    values = [f"{low}{unit}", f"{high}{unit}"]
    return KnowledgeUnitCandidate(
        unit_type="parameter",
        canonical_name=canonical_name,
        title=canonical_name.replace("_", " "),
        content=sentence,
        aliases=_class_tokens(sentence),
        properties={
            "parameter_name": "standard_range",
            "property_type": "standard_range",
            "values": values,
            "range": {"min": low, "max": high, "unit": unit},
            "standard_range_not_calculation": True,
            "condition_key": slugify(sentence[:120], fallback_prefix="condition"),
        },
        source=source,
        confidence=0.82,
        extraction_method="rule_based",
        dedup_key=make_dedup_key("parameter", canonical_name, low, high, unit),
        warnings=[],
    )


def _capability_candidate(sentence: str, source: dict) -> KnowledgeUnitCandidate | None:
    match = COOLING_CAPABILITY_RE.search(sentence)
    if not match or not STANDARD_CLASS_RE.search(sentence):
        return None
    amount, unit, per_target = match.groups()
    canonical_name = _canonical_for(sentence, "cooling_capability")
    value = f"{amount}{unit}"
    if per_target:
        value = f"{value}/per_{per_target.lower()}"
    return KnowledgeUnitCandidate(
        unit_type="parameter",
        canonical_name=canonical_name,
        title=canonical_name.replace("_", " "),
        content=sentence,
        aliases=_class_tokens(sentence),
        properties={
            "parameter_name": "cooling_capability",
            "property_type": "cooling_capability",
            "values": [value],
            "unit": unit,
            "target": per_target,
            "standard_range_not_calculation": True,
            "condition_key": slugify(sentence[:120], fallback_prefix="condition"),
        },
        source=source,
        confidence=0.80,
        extraction_method="rule_based",
        dedup_key=make_dedup_key("parameter", canonical_name, value),
        warnings=[],
    )


def extract(text: str, source: dict) -> list[KnowledgeUnitCandidate]:
    normalized = compact_text(text)
    if not normalized or not STANDARD_CLASS_RE.search(normalized):
        return []

    candidates: list[KnowledgeUnitCandidate] = []
    seen: set[str] = set()
    for sentence in _sentences(normalized):
        candidate = _range_candidate(sentence, source) or _capability_candidate(sentence, source)
        if not candidate or candidate.dedup_key in seen:
            continue
        seen.add(candidate.dedup_key)
        candidates.append(candidate)
    return candidates
