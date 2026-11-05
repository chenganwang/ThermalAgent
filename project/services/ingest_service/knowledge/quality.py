from __future__ import annotations

import re
from typing import Any
import unicodedata

VALID_REVIEW_STATUSES = {"accepted", "rejected", "needs_edit", "duplicate", "pending"}

_NOISE_PATTERNS = [
    re.compile(r"^\s*(contents|table of contents|references|reference)\s*$", re.I),
    re.compile(r"^\s*(目录|参考文献)\s*$"),
    re.compile(r"^\s*\d{1,4}\s*$"),
    re.compile(r"^\s*第?\s*\d+\s*页\s*$"),
]

_VENDOR_CLAIM_RE = re.compile(
    r"best[- ]in[- ]class|industry[- ]leading|guaranteed|revolutionary|领先|最佳|革命性|保证|显著提升|最高性能",
    re.I,
)

_UNIT_RE = re.compile(
    r"(?:°C|℃|\bK\b|\bW\b|\bkW\b|\bPa\b|\bkPa\b|\bMPa\b|L/min|kg/s|kg/m3|J/\(kg\*?K\)|J/kgK|W/\(m\*?K\)|W/mK|%)",
    re.I,
)
_NON_PERCENT_UNIT_RE = re.compile(
    r"(?:°C|℃|\bK\b|\bW\b|\bkW\b|\bPa\b|\bkPa\b|\bMPa\b|L/min|kg/s|kg/m3|J/\(kg\*?K\)|J/kgK|W/\(m\*?K\)|W/mK)",
    re.I,
)

_DEFINITION_RE = re.compile(r"(?:\b(?:is|refers to|provides)\b|是|指|用于|是一种|定义为)", re.I)
_FORMULA_SIGNAL_RE = re.compile(r"(?:\bq\b|\bm_dot\b|\bcp\b|\brho\b|\bmu\b|\btj\b|\bta\b|\bre\b|ΔT|螖T)\s*=|=", re.I)
_PATH_SIGNAL_RE = re.compile(r"->|→|鈫|鉃|鈬|\bto\b.+\bto\b", re.I)
_FAULT_SIGNAL_RE = re.compile(
    r"leak|blockage|blocked|insufficient flow|low flow|overtemperature|temperature rise|pressure drop|"
    r"堵塞|阻塞|泄漏|流量不足|温升|过温|压降",
    re.I,
)
_PARAMETER_SIGNAL_RE = re.compile(
    r"\b(?:EGW|PGW|ASHRAE|OCP|W17|W27|W32|W40|W45|A[1-4])\b|%|℃|°C|掳C|L/min|kg/s|J/kgK|W/mK|物性|参数",
    re.I,
)
_CAUSE_MARKER_RE = re.compile(r"导致|会导致|causes?|results in|leads to|due to", re.I)
_SYMPTOM_FAULT_NAMES = {"insufficient_flow", "overtemperature"}
_PATH_EVIDENCE_RE = re.compile(
    r"->|→|鈫|鉃|鈬|heat transfer path|cooling path|flow path|liquid path|cooling loop|liquid loop|"
    r"fluid loop|liquid circuit|technology cooling system|facility water system|IT loop|facility loop|"
    r"\bfrom\b.+\bto\b|\bthrough\b|散热路径|冷却路径|液冷回路|冷却回路|流路",
    re.I,
)
_STANDARD_RE = re.compile(r"\b(?:ASHRAE|OCP|W17|W27|W32|W40|W45|W\+|A[1-4])\b|water cooling class|dry-bulb", re.I)
_CAPABILITY_RE = re.compile(r"\b(?:can\s+support|supports?|support\s+up\s+to|up\s+to|capacity|capability)\b", re.I)
_VALUE_OR_RANGE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|°C|℃|\bK\b|\bW\b|\bkW\b|\bPa\b|\bkPa\b|\bMPa\b|L/min|LPM|kg/s|kg/m3|"
    r"J/\(kg\*?K\)|J/kgK|W/\(m\*?K\)|W/mK|LPM/kW)|"
    r"\d+(?:\.\d+)?\s*(?:to|-|~|–|—|and)\s*\d+(?:\.\d+)?",
    re.I,
)
_REQUIREMENT_RE = re.compile(
    r"endpoint filtration|filtration required|telemetry|control requirement|monitoring requirement|testing requirement|"
    r"shock and vibration|hydrostatic pressure testing|should be considered|required|requirement|shall|"
    r"过滤要求|测试要求|控制要求|遥测|监控",
    re.I,
)


def _as_dict(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, dict):
        return dict(candidate)
    if hasattr(candidate, "to_dict"):
        try:
            value = candidate.to_dict()
            return dict(value) if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def _nested_source(candidate: dict[str, Any]) -> dict[str, Any]:
    source = candidate.get("source")
    return source if isinstance(source, dict) else {}


def _properties(candidate: dict[str, Any]) -> dict[str, Any]:
    properties = candidate.get("properties")
    return properties if isinstance(properties, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, result))


def _add_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def _looks_noise_like(text: str) -> bool:
    value = _text(text)
    if not value:
        return False
    if any(pattern.search(value) for pattern in _NOISE_PATTERNS):
        return True
    alnum_cjk = re.findall(r"[0-9A-Za-z\u4e00-\u9fff]", value)
    return len(value) > 0 and len(alnum_cjk) / max(1, len(value)) < 0.25


def _has_any(properties: dict[str, Any], names: tuple[str, ...]) -> bool:
    for name in names:
        value = properties.get(name)
        if value not in (None, "", [], {}):
            return True
    return False


def _sentence_count(text: str) -> int:
    parts = [part for part in re.split(r"(?<=[。！？!?；;])\s+|\n+", text) if part.strip()]
    if len(parts) <= 1:
        parts = [part for part in re.split(r"(?<=[。！？!?；;])", text) if part.strip()]
    return len(parts) or (1 if text else 0)


def _content_signal_types(content: str) -> set[str]:
    signals = set()
    if _FORMULA_SIGNAL_RE.search(content):
        signals.add("formula")
    if _PATH_SIGNAL_RE.search(content):
        signals.add("thermal_path")
    if _FAULT_SIGNAL_RE.search(content):
        signals.add("fault_case")
    if _PARAMETER_SIGNAL_RE.search(content):
        signals.add("parameter")
    return signals


def _has_path_evidence(content: str) -> bool:
    return bool(_PATH_EVIDENCE_RE.search(content))


def _has_value_or_range(content: str, properties: dict[str, Any]) -> bool:
    if _has_any(properties, ("value", "values", "range", "unit")):
        return True
    return bool(_VALUE_OR_RANGE_RE.search(content))


def _node_order_from_text(text: str) -> list[str]:
    aliases = [
        ("chip", ["chip", "processor", "芯片", "处理器"]),
        ("tim", ["tim", "thermal interface material", "导热界面材料"]),
        ("cold_plate", ["cold plate", "coldplate", "冷板", "水冷板"]),
        ("coolant", ["coolant", "cooling fluid", "冷却液", "冷却工质"]),
        ("cdu", ["cdu", "cooling distribution unit", "冷却分配单元"]),
        ("it_loop", ["it loop", "secondary loop"]),
        ("facility_loop", ["facility loop", "primary loop"]),
        ("facility_water", ["facility water", "设施水"]),
    ]
    found = []
    lower = text.lower()
    for canonical, names in aliases:
        positions = [lower.find(name.lower()) for name in names if lower.find(name.lower()) >= 0]
        if positions:
            found.append((min(positions), canonical))
    return [name for _, name in sorted(found)]


def _atomicity_checks(candidate: dict[str, Any], flags: list[str]) -> float:
    unit_type = _text(candidate.get("unit_type"))
    content = _text(candidate.get("content"))
    properties = _properties(candidate)
    penalty = 0.0

    if not content:
        return penalty

    signals = _content_signal_types(content)
    if len(content) > 260 or _sentence_count(content) > 2:
        _add_flag(flags, "content_too_broad")
        penalty -= 0.16

    foreign_signals = set(signals)
    if unit_type in foreign_signals:
        foreign_signals.remove(unit_type)
    if unit_type in {"concept", "component"} and len(signals) >= 2:
        _add_flag(flags, "content_contains_multiple_unit_types")
        penalty -= 0.18
    elif unit_type not in {"concept", "component"} and len(foreign_signals) >= 2:
        _add_flag(flags, "content_contains_multiple_unit_types")
        penalty -= 0.14

    if unit_type == "thermal_path":
        expected = properties.get("nodes") or properties.get("path")
        observed = _node_order_from_text(content)
        if not _has_path_evidence(content):
            _add_flag(flags, "thermal_path_without_path_evidence")
            penalty -= 0.22
        if isinstance(expected, list) and observed and [str(x).lower() for x in expected] != observed[: len(expected)]:
            _add_flag(flags, "thermal_path_order_suspicious")
            penalty -= 0.18
        if _STANDARD_RE.search(content) or _CAPABILITY_RE.search(content):
            _add_flag(flags, "standard_range_misclassified")
            penalty -= 0.18

    if unit_type == "parameter":
        name = str(properties.get("parameter_name") or "")
        values = properties.get("values")
        has_value = bool(values) or _has_any(properties, ("value", "range"))
        if properties.get("property_value_missing") is True or (name in {"specific_heat", "density", "viscosity", "thermal_conductivity"} and not has_value):
            _add_flag(flags, "parameter_value_missing")
            penalty -= 0.12
        property_type = str(properties.get("property_type") or "")
        if property_type not in {"standard_range", "cooling_capability"} and not _has_value_or_range(content, properties):
            _add_flag(flags, "parameter_without_value_or_range")
            penalty -= 0.20
        if _REQUIREMENT_RE.search(content) and not _has_value_or_range(content, properties):
            _add_flag(flags, "requirement_sentence_not_knowledge_unit")
            penalty -= 0.18
    elif _REQUIREMENT_RE.search(content) and unit_type not in {"formula", "fault_case"}:
        _add_flag(flags, "requirement_sentence_not_knowledge_unit")
        penalty -= 0.12

    if unit_type == "fault_case":
        fault_name = str(properties.get("fault_name") or candidate.get("canonical_name") or "")
        causes = properties.get("possible_causes")
        if any(symptom in fault_name for symptom in _SYMPTOM_FAULT_NAMES) and not causes and not _CAUSE_MARKER_RE.search(content):
            _add_flag(flags, "symptom_as_fault_case")
            penalty -= 0.18

    return penalty


def _specific_checks(candidate: dict[str, Any], flags: list[str]) -> float:
    unit_type = _text(candidate.get("unit_type"))
    properties = _properties(candidate)
    content = _text(candidate.get("content"))
    title = _text(candidate.get("title"))
    bonus = 0.0

    if unit_type == "formula":
        if _has_any(properties, ("expression", "formula")):
            bonus += 0.12
        else:
            _add_flag(flags, "formula_missing_expression")
            bonus -= 0.20
        variables = properties.get("variables")
        if isinstance(variables, dict) and variables:
            bonus += 0.10
        else:
            _add_flag(flags, "formula_missing_variables")
            bonus -= 0.18
    elif unit_type == "thermal_path":
        nodes = properties.get("nodes") or properties.get("path")
        if isinstance(nodes, list) and len(nodes) >= 2:
            bonus += 0.14
        else:
            _add_flag(flags, "thermal_path_missing_nodes")
            bonus -= 0.22
    elif unit_type == "fault_case":
        if _has_any(properties, ("fault_name", "symptom", "possible_causes")):
            bonus += 0.12
        else:
            _add_flag(flags, "fault_case_missing_fault_fields")
            bonus -= 0.22
    elif unit_type == "component":
        if _has_any(properties, ("role", "connected_to")):
            bonus += 0.10
        else:
            _add_flag(flags, "component_missing_role")
            bonus -= 0.10
    elif unit_type == "parameter":
        if _has_any(properties, ("parameter_name", "value", "values", "range", "property_type")):
            bonus += 0.10
        else:
            _add_flag(flags, "parameter_missing_parameter_fields")
            bonus -= 0.18
        values = properties.get("values")
        has_value_text = bool(values) or bool(re.search(r"\d", f"{title} {content}"))
        unit_re = _UNIT_RE if properties.get("parameter_name") == "concentration" else _NON_PERCENT_UNIT_RE
        property_type = str(properties.get("property_type") or "")
        if property_type in {"standard_range", "cooling_capability"}:
            bonus += 0.08
        if has_value_text and property_type not in {"standard_range", "cooling_capability"} and not (
            unit_re.search(content) or unit_re.search(title) or any(unit_re.search(str(v)) for v in (values or []))
        ):
            _add_flag(flags, "parameter_missing_unit")
            bonus -= 0.12
    elif unit_type == "concept":
        if _DEFINITION_RE.search(content):
            bonus += 0.12
        else:
            _add_flag(flags, "concept_missing_definition_marker")
            bonus -= 0.16
    else:
        _add_flag(flags, "invalid_unit_type")
        bonus -= 0.30

    return bonus


def _review_status(score: float, flags: list[str], confidence: float) -> str:
    if "duplicate_like" in flags:
        return "duplicate"
    hard_reject = {"missing_source", "missing_dedup_key", "invalid_unit_type"}
    if any(flag in flags for flag in hard_reject) and score < 0.45:
        return "rejected"
    if score < 0.40 or confidence < 0.35:
        return "rejected"
    needs_edit_flags = {
        "content_too_broad",
        "content_contains_multiple_unit_types",
        "thermal_path_order_suspicious",
        "thermal_path_without_path_evidence",
        "parameter_value_missing",
        "parameter_without_value_or_range",
        "standard_range_misclassified",
        "requirement_sentence_not_knowledge_unit",
        "symptom_as_fault_case",
        "weak_accepted_candidate",
    }
    if any(flag in flags for flag in needs_edit_flags):
        return "needs_edit"
    if score < 0.70 or confidence < 0.55 or any(flag.endswith("_missing_variables") for flag in flags):
        return "needs_edit"
    return "accepted"


def score_candidate_quality(candidate: dict | Any) -> dict[str, Any]:
    flags: list[str] = []
    try:
        data = _as_dict(candidate)
        source = _nested_source(data)
        properties = _properties(data)

        score = 0.30
        source_preview = _text(source.get("source_text_preview"))
        content = _text(data.get("content"))
        title = _text(data.get("title"))
        canonical_name = _text(data.get("canonical_name"))
        dedup_key = _text(data.get("dedup_key"))
        confidence = _float(data.get("confidence"), 0.0)

        if source_preview:
            score += 0.18
        else:
            _add_flag(flags, "missing_source")
            score -= 0.25

        if source.get("document_id") not in (None, "") or source.get("chunk_id") not in (None, ""):
            score += 0.12
        else:
            _add_flag(flags, "missing_source_ids")
            score -= 0.10

        if source.get("page_no") in (None, ""):
            _add_flag(flags, "missing_page_no")
            score -= 0.03
        else:
            score += 0.03

        if source.get("section_title") in (None, ""):
            _add_flag(flags, "missing_section_title")
            score -= 0.03
        else:
            score += 0.03

        if title or content:
            score += 0.08
        else:
            _add_flag(flags, "missing_title_or_content")
            score -= 0.20

        if len(content) < 12:
            _add_flag(flags, "content_too_short")
            score -= 0.10
        elif len(content) >= 40:
            score += 0.06

        if canonical_name:
            score += 0.06
        else:
            _add_flag(flags, "missing_canonical_name")
            score -= 0.12

        if properties:
            score += 0.05
        else:
            _add_flag(flags, "missing_properties")
            score -= 0.06

        if dedup_key:
            score += 0.07
            tail = dedup_key.split(":", 1)[-1]
            if len(tail) < 3 or tail in {"unknown", "item", "none", "default"}:
                _add_flag(flags, "generic_dedup_key")
                score -= 0.12
        else:
            _add_flag(flags, "missing_dedup_key")
            score -= 0.25

        if source_preview and _looks_noise_like(source_preview):
            _add_flag(flags, "noise_like_source")
            score -= 0.18

        if _VENDOR_CLAIM_RE.search(f"{title} {content} {source_preview}"):
            _add_flag(flags, "vendor_claim_like")
            score -= 0.04

        merged_count = source.get("merged_source_count")
        if isinstance(merged_count, int) and merged_count > 1:
            _add_flag(flags, "duplicate_like")
            _add_flag(flags, "duplicate_like_source")
            score -= 0.10
        if "duplicate_merged" in (data.get("warnings") or []):
            _add_flag(flags, "duplicate_like")
            _add_flag(flags, "duplicate_like_source")
            score -= 0.10

        score += (confidence - 0.5) * 0.28
        if confidence < 0.55:
            _add_flag(flags, "low_confidence")

        score += _specific_checks(data, flags)
        score += _atomicity_checks(data, flags)
        serious_flags = {
            "content_too_broad",
            "content_contains_multiple_unit_types",
            "thermal_path_order_suspicious",
            "thermal_path_without_path_evidence",
            "parameter_value_missing",
            "parameter_without_value_or_range",
            "standard_range_misclassified",
            "requirement_sentence_not_knowledge_unit",
            "symptom_as_fault_case",
            "duplicate_like",
            "missing_source",
        }
        if score >= 0.78 and not serious_flags.intersection(flags):
            if confidence < 0.78 or "missing_section_title" in flags or "missing_page_no" in flags or len(content) < 24:
                _add_flag(flags, "weak_accepted_candidate")
                score -= 0.10
        score = max(0.0, min(1.0, score))
        if score >= 0.78:
            level = "high"
        elif score >= 0.55:
            level = "medium"
        else:
            level = "low"

        return {
            "quality_score": round(score, 3),
            "quality_level": level,
            "quality_flags": flags,
            "recommended_review_status": _review_status(score, flags, confidence),
        }
    except Exception as exc:
        return {
            "quality_score": 0.0,
            "quality_level": "low",
            "quality_flags": [f"quality_scoring_error:{type(exc).__name__}"],
            "recommended_review_status": "needs_edit",
        }


def analyze_chunk_quality(text: str, *, chunk_type: str = "text") -> dict[str, Any]:
    """Label parser/chunk quality without changing the supplied text."""

    value = str(text or "")
    length = len(value)
    issues: list[dict[str, Any]] = []

    def add(code: str, severity: str, count: int | None = None) -> None:
        item: dict[str, Any] = {"code": code, "severity": severity}
        if count is not None:
            item["count"] = int(count)
        if not any(existing["code"] == code for existing in issues):
            issues.append(item)

    if not value.strip():
        add("empty_text", "error")

    replacement_count = value.count("\ufffd")
    unknown_glyph_count = sum(
        1
        for char in value
        if unicodedata.category(char) in {"Cn", "Co", "Cs"} or char in {"\u25a1", "\u25a0"}
    )
    control_count = sum(
        1
        for char in value
        if unicodedata.category(char) == "Cc" and char not in {"\n", "\r", "\t"}
    )
    if replacement_count:
        add("unicode_replacement_character", "error", replacement_count)
    if unknown_glyph_count:
        severity = "error" if unknown_glyph_count / max(1, length) >= 0.02 else "warning"
        add("unknown_glyph", severity, unknown_glyph_count)
    if control_count:
        add("control_character", "error", control_count)

    printable_count = sum(1 for char in value if char.isprintable() or char in {"\n", "\r", "\t"})
    printable_ratio = printable_count / max(1, length)
    if value and printable_ratio < 0.90:
        add("low_printable_ratio", "error")

    meaningful_count = sum(1 for char in value if char.isalnum() or "\u4e00" <= char <= "\u9fff")
    symbol_count = sum(1 for char in value if unicodedata.category(char).startswith(("S", "P")))
    symbol_ratio = symbol_count / max(1, meaningful_count + symbol_count)
    if length >= 40 and symbol_ratio > 0.72:
        add("abnormal_symbol_ratio", "error")
    elif length >= 40 and symbol_ratio > 0.55:
        add("abnormal_symbol_ratio", "warning")

    minimum = {"table": 140, "figure": 20}.get(str(chunk_type or "text"), 80)
    if value.strip() and length < minimum:
        add("extremely_short_chunk", "warning")
    if length > 20_000:
        add("extremely_long_chunk", "warning")

    repeated_run = max((len(match.group(0)) for match in re.finditer(r"(.)\1{7,}", value, re.S)), default=0)
    if repeated_run >= 20:
        add("abnormal_character_repetition", "error", repeated_run)
    elif repeated_run >= 8:
        add("abnormal_character_repetition", "warning", repeated_run)

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    table_like = str(chunk_type or "").lower() == "table" or bool(re.search(r"(?:^|\n)\s*\[?表\]?", value))
    if table_like and len(lines) >= 2:
        delimiter_counts = [line.count("|") + line.count("\t") for line in lines]
        nonzero = [count for count in delimiter_counts if count > 0]
        if nonzero and (len(set(nonzero)) > 1 or len(nonzero) != len(lines)):
            add("table_column_shape_anomaly", "warning")

    formula_signal = bool(re.search(r"[=∑∫√Δ∇]|\b(?:sin|cos|exp|log)\s*\(", value, re.I))
    if formula_signal and re.search(r"(?:[+*/=\-]\s*){5,}", value):
        add("formula_operator_corruption", "error")

    if any(item["severity"] == "error" for item in issues):
        state = "suspected_parse_error"
    elif issues:
        state = "needs_review"
    else:
        state = "normal"
    return {
        "state": state,
        "issues": issues,
        "metrics": {
            "length": length,
            "printable_ratio": round(printable_ratio, 4),
            "symbol_ratio": round(symbol_ratio, 4),
            "replacement_count": replacement_count,
            "unknown_glyph_count": unknown_glyph_count,
            "control_count": control_count,
        },
    }
