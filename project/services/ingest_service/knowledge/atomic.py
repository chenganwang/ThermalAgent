from __future__ import annotations

import re
from typing import Any

from .normalizer import compact_text

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
_FORMULA_RE = re.compile(r"(?:\bq\b|\bm_dot\b|\bcp\b|\bdt\b|\bdelta\s*t\b|ΔT|螖T|rho|mu|tj|ta|rθ|rtheta|re)\s*=", re.I)
_FORMULA_ANY_RE = re.compile(r"(?:=|\bq\b\s*=|\bm_dot\b\s*=|\br\s*=|\btj\s*=|\bre\s*=|Δp|螖p|dp)", re.I)
_PATH_RE = re.compile(r"(?:->|→|鈫|鉃|鈬)")
_FAULT_RE = re.compile(
    r"leak|leakage|blockage|blocked|air bubble|air lock|pump failure|corrosion|contamination|"
    r"insufficient flow|low flow|overtemperature|overheating|temperature rise|pressure drop|"
    r"堵塞|阻塞|泄漏|漏液|气泡|气堵|泵故障|腐蚀|污染|流量不足|温升|过温|压降|"
    r"鍫靛|闃诲|娉勬紡|婕忔|姘旀场|姘斿|鑵愯殌|姹℃煋|娴侀噺涓嶈冻|娓╁崌",
    re.I,
)
_PARAMETER_RE = re.compile(
    r"\b(?:EGW|PGW|ASHRAE|OCP|W17|W27|W32|W40|W45|A[1-4]|cp|rho|mu)\b|"
    r"supply temperature|return temperature|flow rate|pressure drop|specific heat|density|viscosity|"
    r"thermal conductivity|concentration|℃|°C|掳C|%|L/min|kg/s|J/kgK|W/mK|"
    r"供水温度|回水温度|流量|压降|比热|密度|粘度|黏度|导热系数|浓度|物性参数|"
    r"渚涙按|鍥炴按|娴侀噺|鍘嬮檷|姣旂儹|瀵嗗害|绮樺害|榛忓害|瀵肩儹|娴撳害|鐗╂€",
    re.I,
)
_DEFINITION_RE = re.compile(
    r"\b(?:is|refers to|provides|used for|serves as)\b|"
    r"是|指|用于|用来|负责|作用|作为|"
    r"鏄|鎸|鐢ㄤ簬|浣滅敤|璐熻矗|浣滀负",
    re.I,
)
_CAUSE_RE = re.compile(
    r"导致|会导致|引起|造成|使|因为|由于|"
    r"causes?|results in|leads to|due to|because of|"
    r"瀵艰嚧|浼氬|寮曡捣|閫犳垚|鐢变簬",
    re.I,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_for_atomic(text: str) -> str:
    value = compact_text(text)
    value = value.replace("→", " -> ")
    value = value.replace("➔", " -> ")
    value = value.replace("=>", " -> ")
    value = re.sub(r"\s*->\s*", " -> ", value)
    return re.sub(r"\s+", " ", value).strip()


def split_sentences(text: str) -> list[str]:
    value = _normalize_for_atomic(text)
    if not value:
        return []
    parts = [part.strip(" \t\r\n。！？!?；;") for part in _SENTENCE_SPLIT_RE.split(value) if part.strip()]
    if not parts:
        parts = [value]
    out: list[str] = []
    for part in parts:
        if len(part) <= 320:
            out.append(part)
            continue
        chunks = [chunk.strip(" ,，、") for chunk in re.split(r"(?<=[，,、])\s*", part) if chunk.strip(" ,，、")]
        out.extend(chunks or [part[:320].rstrip()])
    return out


def _keyword_variants(keywords: list[str]) -> list[str]:
    out: list[str] = []
    for keyword in keywords or []:
        item = _text(keyword)
        if not item:
            continue
        out.append(item)
        out.append(item.replace("_", " "))
    return list(dict.fromkeys(out))


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    for keyword in _keyword_variants(keywords):
        if keyword.lower() in lower:
            return True
    return False


def _candidate_keywords(candidate: dict[str, Any]) -> list[str]:
    props = candidate.get("properties") if isinstance(candidate.get("properties"), dict) else {}
    aliases = candidate.get("aliases") if isinstance(candidate.get("aliases"), list) else []
    values = [
        candidate.get("canonical_name"),
        candidate.get("title"),
        props.get("parameter_name"),
        props.get("fault_name"),
        props.get("expression"),
    ]
    values.extend(aliases)
    return [_text(value) for value in values if _text(value)]


def extract_atomic_sentence(text: str, keywords: list[str]) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return ""
    if not keywords:
        return sentences[0]
    for sentence in sentences:
        if _contains_keyword(sentence, keywords):
            return sentence
    return ""


def _formula_content(candidate: dict[str, Any], content: str) -> str:
    props = candidate.get("properties") if isinstance(candidate.get("properties"), dict) else {}
    expression = _text(props.get("expression") or props.get("formula") or candidate.get("title"))
    variables = props.get("variables")
    if isinstance(variables, dict) and variables:
        variables_text = ", ".join(f"{key}={value}" for key, value in variables.items())
        return f"{expression}; variables: {variables_text}" if expression else f"variables: {variables_text}"
    for sentence in split_sentences(content):
        if _FORMULA_ANY_RE.search(sentence):
            return sentence
    return expression


def _path_content(content: str) -> str:
    sentences = split_sentences(content)
    for sentence in sentences:
        if _PATH_RE.search(sentence) or " to " in sentence.lower():
            return sentence
    return ""


def _parameter_content(candidate: dict[str, Any], content: str) -> str:
    props = candidate.get("properties") if isinstance(candidate.get("properties"), dict) else {}
    keywords = _candidate_keywords(candidate)
    values = props.get("values") if isinstance(props.get("values"), list) else []
    keywords.extend(str(value) for value in values if value not in (None, ""))
    for sentence in split_sentences(content):
        if _contains_keyword(sentence, keywords) or _PARAMETER_RE.search(sentence):
            if _FAULT_RE.search(sentence) and not re.search(r"\d|%|EGW|PGW|cp|rho|mu|℃|°C|掳C|L/min|kg/s", sentence, re.I):
                continue
            return sentence
    return ""


def _definition_or_role_content(candidate: dict[str, Any], content: str) -> str:
    keywords = _candidate_keywords(candidate)
    fallback = ""
    for sentence in split_sentences(content):
        if not _contains_keyword(sentence, keywords):
            continue
        if _DEFINITION_RE.search(sentence):
            return sentence
        if not fallback and not (_FORMULA_ANY_RE.search(sentence) or _PATH_RE.search(sentence) or _FAULT_RE.search(sentence)):
            fallback = sentence
    return fallback


def _fault_content(content: str) -> str:
    for sentence in split_sentences(content):
        if _FAULT_RE.search(sentence) and (_CAUSE_RE.search(sentence) or "risk" in sentence.lower() or "风险" in sentence):
            return sentence
    for sentence in split_sentences(content):
        if _FAULT_RE.search(sentence):
            return sentence
    return ""


def _looks_non_atomic(unit_type: str, content: str) -> bool:
    if len(content) > 260:
        return True
    sentence_count = len(split_sentences(content))
    if sentence_count > 2:
        return True
    signals = 0
    if _FORMULA_ANY_RE.search(content):
        signals += 1
    if _PATH_RE.search(content):
        signals += 1
    if _FAULT_RE.search(content):
        signals += 1
    if _PARAMETER_RE.search(content):
        signals += 1
    if unit_type in {"concept", "component"} and signals >= 2:
        return True
    return signals >= 3


def split_candidate_content_by_unit_type(candidate: dict) -> dict:
    data = dict(candidate or {})
    unit_type = _text(data.get("unit_type"))
    content = _text(data.get("content"))
    if not content:
        return data

    selected = ""
    if unit_type == "formula":
        selected = _formula_content(data, content)
    elif unit_type == "parameter":
        selected = _parameter_content(data, content)
    elif unit_type == "thermal_path":
        selected = _path_content(content)
    elif unit_type == "fault_case":
        selected = _fault_content(content)
    elif unit_type in {"concept", "component"}:
        selected = _definition_or_role_content(data, content)

    if selected:
        data["content"] = selected.strip()
        return data

    if _looks_non_atomic(unit_type, content):
        warnings = list(data.get("warnings") or [])
        if "content_not_atomic" not in warnings:
            warnings.append("content_not_atomic")
        data["warnings"] = warnings
    return data
