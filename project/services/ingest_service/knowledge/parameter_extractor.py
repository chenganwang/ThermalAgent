from __future__ import annotations

import re

from .atomic import split_sentences
from .contracts import KnowledgeUnitCandidate
from .normalizer import compact_text, make_dedup_key, sentence_windows, slugify

PARAMETER_PATTERNS: list[tuple[str, re.Pattern[str], list[str]]] = [
    ("supply_temperature", re.compile(r"supply temperature|供水温度|供液温度|入口水温|inlet water temperature|渚涙按娓╁害|渚涙恫娓╁害|鍏ュ彛姘存俯", re.I), ["temperature"]),
    ("return_temperature", re.compile(r"return temperature|回水温度|回液温度|出口水温|outlet water temperature|鍥炴按娓╁害|鍥炴恫娓╁害|鍑哄彛姘存俯", re.I), ["temperature"]),
    ("water_temperature_class", re.compile(r"\bW(?:17|27|32|40|45|\+)\b", re.I), ["ASHRAE", "OCP", "water_class"]),
    ("ashrae_environment_class", re.compile(r"\bA[1-4]\b", re.I), ["ASHRAE", "air_class"]),
    ("flow_rate", re.compile(r"flow rate|mass flow|volume flow|流量|娴侀噺", re.I), ["flow"]),
    ("pressure_drop", re.compile(r"pressure drop|压降|压力损失|Δp|螖p|dp|鍘嬮檷|鍘嬪姏鎹熷け", re.I), ["pressure"]),
    ("specific_heat", re.compile(r"\bcp\b|c_p|specific heat|比热|比热容|姣旂儹|姣旂儹瀹?", re.I), ["property"]),
    ("density", re.compile(r"\brho\b|density|密度|瀵嗗害", re.I), ["property"]),
    ("viscosity", re.compile(r"\bmu\b|viscosity|粘度|黏度|绮樺害|榛忓害", re.I), ["property"]),
    ("thermal_conductivity", re.compile("thermal conductivity|\\u5bfc\\u70ed\\u7cfb\\u6570|\\bk\\b|\\u7025\\u80a9\\u5139\\u7eef\\u7ed8\\u669f", re.I), ["property"]),
    ("concentration", re.compile(r"\b\d{1,3}\s*%\s*(?:EGW|PGW|ethylene glycol|propylene glycol)|浓度|质量分数|体积分数|娴撳害|璐ㄩ噺鍒嗘暟|浣撶Н鍒嗘暟", re.I), ["fluid_mixture"]),
]

VALUE_RE = re.compile(
    r"[-+]?\d+(?:\.\d+)?\s*(?:%|℃|°C|掳C|鈩.?|C|K|W|kW|Pa|kPa|MPa|L/min|LPM|kg/s|kg/m3|J/\(kg\*K\)|J/kgK|W/\(m\*K\)|W/mK|LPM/kW)?",
    re.I,
)

VALUE_WITH_UNIT_RE = re.compile(
    r"[-+]?\d+(?:\.\d+)?\s*(?:%|℃|°C|掳C|K\b|W\b|kW\b|Pa\b|kPa\b|MPa\b|L/min|LPM|kg/s|kg/m3|"
    r"J/\(kg\*K\)|J/kgK|W/\(m\*K\)|W/mK|LPM/kW)",
    re.I,
)
RANGE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:to|-|~|–|—|and)\s*\d+(?:\.\d+)?", re.I)
_FLOW_UNIT_RE = re.compile(r"\b(?:L/min|lpm|LPM|kg/s|m3/s|m\^3/s|gpm|LPM/kW)\b", re.I)
_FLOW_SYMPTOM_RE = re.compile(r"流量不足|低流量|insufficient flow|low flow|娴侀噺涓嶈冻", re.I)
_PRESSURE_UNIT_RE = re.compile(r"\b(?:Pa|kPa|MPa|bar|psi)\b", re.I)
_PROPERTY_VALUE_UNIT_RE = re.compile(r"J/\(kg\*?K\)|J/kgK|kg/m3|Pa\*?s|mPa\*?s|W/\(m\*?K\)|W/mK", re.I)
_STANDARD_OR_CAPABILITY_RE = re.compile(r"\b(?:ASHRAE|OCP|W17|W27|W32|W40|W45|W\+|A[1-4])\b", re.I)
_CAPABILITY_RE = re.compile(r"\b(?:can\s+support|supports?|support\s+up\s+to|up\s+to|capacity|capability)\b", re.I)
_REQUIREMENT_RE = re.compile(
    r"endpoint filtration|filtration required|telemetry|control requirement|monitoring requirement|testing requirement|"
    r"shock and vibration|hydrostatic pressure testing|should be considered|required|requirement|shall|"
    r"过滤要求|测试要求|控制要求|遥测|监控",
    re.I,
)


def _context_name(text: str, parameter_name: str) -> str:
    lower = text.lower()
    if "egw" in lower or "ethylene glycol" in lower:
        return f"egw_{parameter_name}"
    if "pgw" in lower or "propylene glycol" in lower:
        return f"pgw_{parameter_name}"
    if "ashrae" in lower:
        return f"ashrae_{parameter_name}"
    if "ocp" in lower:
        return f"ocp_{parameter_name}"
    return parameter_name


def _evidence_for_pattern(text: str, pattern: re.Pattern[str]) -> str:
    matches = []
    for sentence in split_sentences(text) + sentence_windows(text):
        parts = re.split(r"(?<=[A-Za-z0-9\)])\.\s+(?=[A-Z])", sentence)
        for part in parts:
            item = part.strip(" 。.;；")
            if pattern.search(item):
                matches.append(item)
    for sentence in matches:
        if "=" not in sentence or re.search(r"\b(?:EGW|PGW|ethylene glycol|propylene glycol|specific heat|density|viscosity)\b|物性|参数|浓度", sentence, re.I):
            return sentence
    return matches[0] if matches else ""


def _has_value_or_range(evidence: str) -> bool:
    return bool(VALUE_WITH_UNIT_RE.search(evidence) or RANGE_RE.search(evidence))


def _has_parameter_context(parameter_name: str, evidence: str, values: list[str], tags: list[str]) -> bool:
    if _REQUIREMENT_RE.search(evidence) and not _has_value_or_range(evidence):
        return False
    if set(tags) & {"ASHRAE", "OCP", "water_class", "air_class"}:
        return False
    if "fluid_mixture" in tags:
        return bool(re.search(r"\d{1,3}\s*%", evidence))
    if parameter_name == "flow_rate":
        return bool(_FLOW_UNIT_RE.search(evidence) or (RANGE_RE.search(evidence) and re.search(r"flow rate|mass flow|volume flow|流量", evidence, re.I)))
    if parameter_name == "pressure_drop":
        return bool(_PRESSURE_UNIT_RE.search(evidence) or re.search(r"(?:Δp|dp)\s*=", evidence, re.I))
    if parameter_name in {"supply_temperature", "return_temperature"}:
        return bool(re.search(r"℃|°C|K\b", evidence, re.I) or RANGE_RE.search(evidence))
    if parameter_name in {"specific_heat", "density", "viscosity", "thermal_conductivity"}:
        return bool(
            re.search(r"\b(?:EGW|PGW|ethylene glycol|propylene glycol)\b|物性参数|鐗╂€", evidence, re.I)
            or _PROPERTY_VALUE_UNIT_RE.search(evidence)
        )
    if set(tags) & {"fluid_mixture"}:
        return True
    if values:
        return True
    return bool(re.search(r"\b(?:EGW|PGW|ethylene glycol|propylene glycol|specific heat|density|viscosity)\b|物性参数|鐗╂€", evidence, re.I))


def _is_flow_symptom_only(evidence: str) -> bool:
    if not _FLOW_SYMPTOM_RE.search(evidence):
        return False
    if _FLOW_UNIT_RE.search(evidence):
        return False
    if re.search(r"(?:flow rate|mass flow|volume flow|流量)\s*(?:=|为|is|:)", evidence, re.I):
        return False
    return True


def _property_value_missing(parameter_name: str, evidence: str) -> bool:
    if parameter_name not in {"specific_heat", "density", "viscosity", "thermal_conductivity"}:
        return False
    return not _PROPERTY_VALUE_UNIT_RE.search(evidence)


def extract(text: str, source: dict) -> list[KnowledgeUnitCandidate]:
    normalized = compact_text(text)
    if not normalized:
        return []

    candidates: list[KnowledgeUnitCandidate] = []
    for parameter_name, pattern, tags in PARAMETER_PATTERNS:
        if not pattern.search(normalized):
            continue
        evidence = _evidence_for_pattern(normalized, pattern)
        if not evidence:
            continue
        if parameter_name in {"water_temperature_class", "ashrae_environment_class"}:
            continue
        if _STANDARD_OR_CAPABILITY_RE.search(evidence) and _CAPABILITY_RE.search(evidence):
            continue
        if parameter_name == "flow_rate" and _is_flow_symptom_only(evidence):
            continue

        values = VALUE_RE.findall(evidence)
        if not _has_parameter_context(parameter_name, evidence, values, tags):
            continue

        canonical_name = _context_name(evidence, parameter_name)
        warnings = []
        if "property" in tags and not values:
            warnings.append("parameter_without_explicit_value")
        if _property_value_missing(parameter_name, evidence):
            warnings.append("parameter_value_missing")
        candidates.append(
            KnowledgeUnitCandidate(
                unit_type="parameter",
                canonical_name=canonical_name,
                title=canonical_name.replace("_", " "),
                content=evidence,
                aliases=[parameter_name],
                properties={
                    "parameter_name": parameter_name,
                    "values": values[:12],
                    "tags": tags,
                    "standard_range_not_calculation": bool(set(tags) & {"ASHRAE", "OCP", "water_class", "air_class"}),
                    "condition_key": slugify(evidence[:120], fallback_prefix="condition"),
                    "property_value_missing": _property_value_missing(parameter_name, evidence),
                },
                source=source,
                confidence=0.72 if values else 0.58,
                extraction_method="rule_based",
                dedup_key=make_dedup_key("parameter", canonical_name, evidence[:80]),
                warnings=warnings,
            )
        )
    return candidates
