from __future__ import annotations

import re

from .atomic import split_sentences
from .contracts import KnowledgeUnitCandidate
from .normalizer import TERM_ALIASES, compact_text, contains_alias, make_dedup_key, sentence_windows

FAULT_KEYWORDS = {
    "leakage": ["leakage", "leak", "泄漏", "漏液"],
    "blockage": ["blockage", "blocked", "堵塞", "阻塞"],
    "air_bubble": ["air bubble", "air lock", "气泡", "气堵"],
    "pump_failure": ["pump failure", "pump fault", "泵故障", "泵失效"],
    "corrosion": ["corrosion", "腐蚀"],
    "contamination": ["contamination", "污染", "冷却液污染"],
    "insufficient_flow": ["insufficient flow", "low flow", "流量不足", "低流量"],
    "overtemperature": ["overtemperature", "overheating", "temperature rise", "温升升高", "过温", "超温"],
    "pressure_drop": ["pressure drop", "压降"],
    "maintenance_risk": ["maintenance risk", "维护风险"],
}

EXTRA_COMPONENT_ALIASES = {
    "cold_plate": ["冷板", "水冷板"],
    "coolant": ["冷却液", "冷却工质"],
    "chip": ["芯片", "处理器"],
    "tim": ["导热界面材料"],
    "cdu": ["冷却分配单元"],
    "pump": ["泵"],
    "manifold": ["歧管", "分液器"],
}

MITIGATION_MARKERS = ["mitigation", "mitigate", "建议", "处理", "维护", "清洗", "过滤", "排气", "检查"]
CAUSE_MARKER_RE = re.compile(r"会导致|导致|引起|造成|使|causes?|results in|leads to|due to", re.I)
SYMPTOM_FAULTS = {"insufficient_flow", "overtemperature"}


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def _affected_components(text: str) -> list[str]:
    out: list[str] = []
    for canonical, aliases in TERM_ALIASES.items():
        all_aliases = list(aliases or []) + EXTRA_COMPONENT_ALIASES.get(canonical, [])
        if contains_alias(text, all_aliases) or _contains_any(text, all_aliases):
            out.append(canonical)
    return list(dict.fromkeys(out))


def _faults_in_text(text: str) -> list[str]:
    out = []
    for fault_name, keywords in FAULT_KEYWORDS.items():
        if _contains_any(text, keywords):
            out.append(fault_name)
    return out


def _split_cause_effect(text: str) -> tuple[str, str]:
    match = CAUSE_MARKER_RE.search(text)
    if not match:
        return "", ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def _symptoms_from_text(text: str) -> list[str]:
    symptoms = []
    for name in ("insufficient_flow", "overtemperature", "pressure_drop"):
        if _contains_any(text, FAULT_KEYWORDS.get(name, [])):
            symptoms.append(name)
    return list(dict.fromkeys(symptoms))


def _possible_causes(text: str, primary_fault: str) -> list[str]:
    causes = []
    if primary_fault:
        if primary_fault == "blockage":
            causes.append("blockage")
        else:
            causes.append(primary_fault)
    if _contains_any(text, FAULT_KEYWORDS["corrosion"]):
        causes.append("corrosion")
    if _contains_any(text, FAULT_KEYWORDS["contamination"]):
        causes.append("contamination")
    return list(dict.fromkeys(causes))


def _mitigation(text: str) -> list[str]:
    if not any(marker.lower() in text.lower() for marker in MITIGATION_MARKERS):
        return []
    snippets = []
    for sentence in split_sentences(text) + sentence_windows(text):
        if any(marker.lower() in sentence.lower() for marker in MITIGATION_MARKERS):
            snippets.append(sentence)
    return snippets[:3]


def _canonical_fault_name(fault_name: str, components: list[str]) -> str:
    if fault_name == "blockage" and "cold_plate" in components:
        return "cold_plate_blockage"
    if fault_name == "leakage" and components:
        return f"{components[0]}_leakage"
    if fault_name == "pump_failure":
        return "pump_failure"
    return fault_name


def _build_candidate(sentence: str, fault_name: str, source: dict, *, symptoms: list[str] | None = None) -> KnowledgeUnitCandidate:
    components = _affected_components(sentence)
    canonical_name = _canonical_fault_name(fault_name, components)
    symptoms = list(dict.fromkeys(symptoms or _symptoms_from_text(sentence)))
    possible_causes = _possible_causes(sentence, fault_name)
    warnings: list[str] = []
    if fault_name in SYMPTOM_FAULTS and not possible_causes:
        warnings.append("symptom_as_fault_case")
    return KnowledgeUnitCandidate(
        unit_type="fault_case",
        canonical_name=canonical_name,
        title=canonical_name.replace("_", " "),
        content=sentence.strip(" 。.;；"),
        aliases=FAULT_KEYWORDS.get(fault_name, []),
        properties={
            "fault_name": canonical_name,
            "symptom": ", ".join(symptoms),
            "symptoms": symptoms,
            "possible_causes": possible_causes,
            "affected_components": components,
            "mitigation": _mitigation(sentence),
        },
        source=source,
        confidence=0.78 if components else 0.62,
        extraction_method="rule_based",
        dedup_key=make_dedup_key("fault_case", canonical_name),
        warnings=warnings,
    )


def _extract_from_causal_sentence(sentence: str, source: dict) -> KnowledgeUnitCandidate | None:
    cause_text, effect_text = _split_cause_effect(sentence)
    if not cause_text or not effect_text:
        return None
    cause_faults = [fault for fault in _faults_in_text(cause_text) if fault not in SYMPTOM_FAULTS]
    if not cause_faults:
        return None
    symptoms = _symptoms_from_text(effect_text)
    return _build_candidate(sentence, cause_faults[0], source, symptoms=symptoms)


def extract(text: str, source: dict) -> list[KnowledgeUnitCandidate]:
    normalized = compact_text(text)
    if not normalized:
        return []

    candidates: list[KnowledgeUnitCandidate] = []
    seen_sentences: set[str] = set()
    for sentence in split_sentences(normalized) + sentence_windows(normalized):
        if sentence in seen_sentences:
            continue
        seen_sentences.add(sentence)
        faults = _faults_in_text(sentence)
        if not faults:
            continue

        causal = _extract_from_causal_sentence(sentence, source)
        if causal:
            candidates.append(causal)
            continue

        for fault_name in faults:
            if fault_name in SYMPTOM_FAULTS:
                continue
            candidates.append(_build_candidate(sentence, fault_name, source))
    return candidates
