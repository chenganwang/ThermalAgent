from __future__ import annotations

import re

from .atomic import split_sentences
from .contracts import KnowledgeUnitCandidate
from .normalizer import TERM_ALIASES, compact_text, display_name, make_dedup_key, sentence_windows

COMPONENTS = {
    "chip",
    "cpu",
    "gpu",
    "tim",
    "cold_plate",
    "coolant",
    "cdu",
    "pump",
    "manifold",
    "rack_manifold",
    "hose",
    "connector",
    "heat_exchanger",
    "facility_water",
}

ROLES = {
    "chip": "heat_source",
    "cpu": "heat_source",
    "gpu": "heat_source",
    "tim": "thermal_interface",
    "cold_plate": "heat_exchange",
    "coolant": "heat_transport",
    "cdu": "coolant_distribution_and_heat_exchange",
    "pump": "flow_generation",
    "manifold": "flow_distribution",
    "rack_manifold": "rack_flow_distribution",
    "hose": "fluid_connection",
    "connector": "fluid_connection",
    "heat_exchanger": "heat_rejection",
    "facility_water": "facility_side_heat_sink",
}

DEFAULT_CONNECTIONS = {
    "chip": ["TIM"],
    "cpu": ["TIM"],
    "gpu": ["TIM"],
    "tim": ["chip", "cold_plate"],
    "cold_plate": ["TIM", "coolant"],
    "coolant": ["cold_plate", "CDU"],
    "cdu": ["coolant", "facility_water"],
    "pump": ["coolant"],
    "manifold": ["hose", "cold_plate"],
    "rack_manifold": ["manifold", "CDU"],
    "hose": ["connector", "manifold"],
    "connector": ["hose", "cold_plate"],
    "heat_exchanger": ["coolant", "facility_water"],
    "facility_water": ["heat_exchanger", "CDU"],
}

EXTRA_ALIASES: dict[str, list[str]] = {
    "cdu": ["冷却分配单元"],
    "rpu": ["储液泵单元"],
    "tcs": ["技术冷却系统"],
    "cold_plate": ["冷板", "水冷板"],
    "manifold": ["歧管", "分液器"],
    "rack_manifold": ["机架歧管", "机柜歧管"],
    "facility_water": ["设施水", "一次侧水"],
    "chip": ["芯片", "处理器"],
    "tim": ["导热界面材料"],
    "coolant": ["冷却液", "冷却工质"],
    "pump": ["泵"],
    "hose": ["软管"],
    "connector": ["接头", "连接器"],
    "heat_exchanger": ["换热器", "热交换器"],
}

RISK_KEYWORDS = {
    "leakage": ["leakage", "leak", "泄漏", "漏液", "娉勬紡", "婕忔"],
    "pressure_drop": ["pressure drop", "压降", "鍘嬮檷"],
    "blockage": ["blockage", "blocked", "堵塞", "阻塞", "鍫靛", "闃诲"],
    "corrosion": ["corrosion", "腐蚀", "鑵愯殌"],
    "contamination": ["contamination", "污染", "姹℃煋"],
    "maintenance": ["maintenance", "维护", "缁存姢"],
}

_ROLE_RE = re.compile(
    r"\b(?:is|refers to|provides|used for|connects|distributes|transports|role)\b|"
    r"是|指|用于|用来|负责|作用|连接|分配|输送|换热|"
    r"鏄|鎸|鐢ㄤ簬|璐熻矗|浣滅敤|杩炴帴|鍒嗛厤|鎹㈢儹",
    re.I,
)
_FORMULA_OR_PATH_RE = re.compile(r"=|->|→|鈫|鉃|鈬")
_FAULT_RE = re.compile(r"leak|blockage|blocked|堵塞|阻塞|泄漏|流量不足|温升|overtemperature|insufficient flow", re.I)


def _aliases_for(canonical: str) -> list[str]:
    return list(dict.fromkeys(list(TERM_ALIASES.get(canonical, [canonical])) + EXTRA_ALIASES.get(canonical, [])))


def _contains_alias(text: str, aliases: list[str]) -> bool:
    lower = text.lower()
    return any(alias.lower() in lower for alias in aliases)


def _risks(text: str) -> list[str]:
    lower = text.lower()
    out: list[str] = []
    for risk, keywords in RISK_KEYWORDS.items():
        if any(keyword.lower() in lower for keyword in keywords):
            out.append(risk)
    return out


def _component_sentence(text: str, aliases: list[str]) -> str:
    fallback = ""
    for sentence in split_sentences(text):
        if not _contains_alias(sentence, aliases):
            continue
        lower = sentence.lower()
        alias_pos = min((lower.find(alias.lower()) for alias in aliases if alias.lower() in lower), default=-1)
        role_match = _ROLE_RE.search(sentence)
        if role_match and alias_pos >= 0 and alias_pos <= role_match.start():
            return sentence.strip(" 。.;；")
        if _ROLE_RE.search(sentence):
            continue
        if not fallback and not _FORMULA_OR_PATH_RE.search(sentence) and not _FAULT_RE.search(sentence):
            fallback = sentence.strip(" 。.;；")
    return fallback


def extract(text: str, source: dict) -> list[KnowledgeUnitCandidate]:
    normalized = compact_text(text)
    if not normalized:
        return []
    risks = _risks(normalized)

    candidates: list[KnowledgeUnitCandidate] = []
    for canonical in sorted(COMPONENTS):
        aliases = _aliases_for(canonical)
        if not _contains_alias(normalized, aliases):
            continue
        evidence = _component_sentence(normalized, aliases)
        if not evidence:
            continue
        display = display_name(canonical)
        confidence = 0.70 if risks or _ROLE_RE.search(evidence) else 0.62
        candidates.append(
            KnowledgeUnitCandidate(
                unit_type="component",
                canonical_name=canonical,
                title=display,
                content=evidence,
                aliases=aliases,
                properties={
                    "role": ROLES.get(canonical, "component"),
                    "connected_to": DEFAULT_CONNECTIONS.get(canonical, []),
                    "risks": risks,
                    "frontend_hint": "component_node",
                },
                source=source,
                confidence=confidence,
                extraction_method="rule_based",
                dedup_key=make_dedup_key("component", canonical),
                warnings=[],
            )
        )
    return candidates
