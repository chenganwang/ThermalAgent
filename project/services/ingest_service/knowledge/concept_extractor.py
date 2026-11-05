from __future__ import annotations

from .atomic import split_sentences
from .contracts import KnowledgeUnitCandidate
from .normalizer import TERM_ALIASES, compact_text, display_name, make_dedup_key, sentence_windows

EXTRA_ALIASES: dict[str, list[str]] = {
    "cdu": ["冷却分配单元"],
    "rpu": ["储液泵单元"],
    "tcs": ["技术冷却系统"],
    "cold_plate": ["冷板", "水冷板"],
    "direct_liquid_cooling": ["直接液冷"],
    "immersion_cooling": ["浸没式液冷", "浸没液冷"],
    "manifold": ["歧管", "分液器"],
    "rack_manifold": ["机架歧管", "机柜歧管"],
    "facility_water": ["设施水", "一次侧水"],
    "chip": ["芯片", "处理器"],
    "tim": ["导热界面材料"],
    "coolant": ["冷却液", "冷却工质"],
    "pump": ["泵"],
    "heat_exchanger": ["换热器", "热交换器"],
}

_DEFINITION_MARKERS = [
    "是",
    "指",
    "用于",
    "用来",
    "负责",
    "作用",
    "作为",
    "鏄",
    "鎸",
    "鐢ㄤ簬",
    "浣滅敤",
    "浣滀负",
    "is",
    "refers to",
    "provides",
    "used for",
    "serves as",
]


def _aliases_for(canonical: str, aliases: list[str]) -> list[str]:
    return list(dict.fromkeys(list(aliases or []) + EXTRA_ALIASES.get(canonical, [])))


def _contains_alias(sentence: str, alias: str) -> bool:
    return alias.lower() in sentence.lower()


def _definition_sentence_for_alias(text: str, alias: str) -> str:
    for sentence in split_sentences(text):
        lower = sentence.lower()
        if not _contains_alias(sentence, alias):
            continue
        alias_pos = lower.find(alias.lower())
        marker_positions = [lower.find(marker.lower()) for marker in _DEFINITION_MARKERS if marker.lower() in lower]
        marker_pos = min(marker_positions) if marker_positions else -1
        if marker_pos >= 0 and alias_pos <= marker_pos:
            return sentence.strip(" 。.;；")
    return ""


def extract(text: str, source: dict) -> list[KnowledgeUnitCandidate]:
    normalized = compact_text(text)
    if not normalized:
        return []

    lower = normalized.lower()
    candidates: list[KnowledgeUnitCandidate] = []
    for canonical, base_aliases in TERM_ALIASES.items():
        aliases = _aliases_for(canonical, base_aliases)
        matched_alias = ""
        sentence = ""
        for alias in sorted(aliases, key=len, reverse=True):
            if alias.lower() not in lower:
                continue
            sentence = _definition_sentence_for_alias(normalized, alias)
            if sentence:
                matched_alias = alias
                break
        if not matched_alias:
            continue
        if not any(marker.lower() in sentence.lower() for marker in _DEFINITION_MARKERS):
            continue

        title = f"{display_name(canonical)} concept"
        candidates.append(
            KnowledgeUnitCandidate(
                unit_type="concept",
                canonical_name=canonical,
                title=title,
                content=sentence,
                aliases=aliases,
                properties={"definition_markers": [m for m in _DEFINITION_MARKERS if m.lower() in sentence.lower()]},
                source=source,
                confidence=0.78,
                extraction_method="rule_based",
                dedup_key=make_dedup_key("concept", canonical),
                warnings=[],
            )
        )
    return candidates
