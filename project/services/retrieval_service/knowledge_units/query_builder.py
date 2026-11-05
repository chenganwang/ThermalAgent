from __future__ import annotations

from collections import Counter
import re
from typing import Any

from .stopwords import LOW_VALUE_MATCH_TERMS, filter_stopwords, is_stopword, normalize_stopword_term


ALLOWED_UNIT_TYPES = {
    "concept",
    "formula",
    "parameter",
    "component",
    "thermal_path",
    "fault_case",
}

SEARCHABLE_COLUMNS = (
    "unit_code",
    "dedup_key",
    "unit_type",
    "canonical_name",
    "title",
    "summary",
    "content",
    "keywords",
    "meta_json",
)

SELECTABLE_COLUMNS = (
    "id",
    "unit_code",
    "dedup_key",
    "unit_type",
    "canonical_name",
    "title",
    "summary",
    "content",
    "document_id",
    "source_doc_id",
    "source_chunk_id",
    "provenance_status",
    "keywords",
    "meta_json",
    "updated_at",
    "created_at",
)

DOMAIN_ALIASES = {
    "cdu": ("cdu", "cooling_distribution_unit"),
    "gpu": ("gpu",),
    "pgw": ("pgw", "propylene_glycol_water"),
    "tim": ("tim", "thermal_interface_material"),
    "cold": ("cold",),
    "plate": ("plate",),
    "leak": ("leakage", "leak"),
    "leakage": ("leakage", "leak"),
    "contamination": ("contamination", "debris"),
    "debris": ("contamination", "debris"),
    "coolant": ("coolant",),
    "hose": ("hose",),
    "flow": ("flow", "flow_rate"),
    "rate": ("rate", "flow_rate"),
    "pressure": ("pressure", "pressure_drop"),
    "drop": ("drop", "pressure_drop"),
    "concentration": ("concentration", "pgw_concentration"),
    "failure": ("fault", "fault_case"),
    "fault": ("fault", "fault_case"),
    "abnormal": ("fault", "fault_case"),
    "冷却液": ("coolant",),
    "冷却": ("coolant", "cooling"),
    "污染": ("contamination", "debris"),
    "泄漏": ("leakage", "leak"),
    "漏液": ("leakage", "leak"),
    "流量": ("flow_rate", "flow"),
    "压降": ("pressure_drop", "pressure", "drop"),
    "压力": ("pressure",),
    "软管": ("hose",),
    "冷板": ("cold_plate", "cold", "plate"),
    "浓度": ("concentration", "pgw_concentration"),
    "部件": ("component",),
    "故障": ("fault", "fault_case"),
    "温升": ("temperature_rise",),
    "热阻": ("thermal_resistance",),
    "接触热阻": ("contact_thermal_resistance",),
}

PHRASE_ALIASES = {
    "cold plate leakage": ("cold_plate_leakage", "cold_plate", "leakage"),
    "cold plate leak": ("cold_plate_leakage", "cold_plate", "leakage", "leak"),
    "cold plate": ("cold_plate", "cold", "plate"),
    "contact thermal resistance": ("contact_thermal_resistance", "thermal_resistance"),
    "cooling distribution unit": ("cdu", "cooling_distribution_unit"),
    "cdu leakage": ("cdu_leakage", "cdu", "leakage"),
    "flow rate": ("flow_rate", "flow", "rate"),
    "full loop flow rate": ("flow_rate", "flow", "rate"),
    "heat dissipation": ("heat_dissipation",),
    "heat transfer": ("heat_transfer",),
    "inlet temperature": ("inlet_temperature",),
    "liquid cooling": ("liquid_cooling", "coolant"),
    "outlet temperature": ("outlet_temperature",),
    "pgw concentration": ("pgw_concentration", "pgw", "concentration"),
    "pressure drop": ("pressure_drop", "pressure", "drop"),
    "temperature rise": ("temperature_rise",),
    "thermal interface material": ("tim", "thermal_interface_material"),
    "thermal resistance": ("thermal_resistance",),
    "冷板泄漏": ("cold_plate_leakage", "cold_plate", "leakage"),
    "冷却液": ("coolant",),
    "入口温度": ("inlet_temperature",),
    "出口温度": ("outlet_temperature",),
    "接触热阻": ("contact_thermal_resistance", "thermal_resistance"),
}

UNIT_TYPE_INTENT_TERMS = {
    "concept": {
        "concept",
        "coolant",
        "definition",
        "define",
        "liquid_cooling",
        "meaning",
        "principle",
        "role",
        "what",
        "why",
        "是什么",
        "定义",
        "概念",
        "原理",
    },
    "parameter": {
        "parameter",
        "value",
        "values",
        "range",
        "unit",
        "units",
        "number",
        "ratio",
        "lpm",
        "kw",
        "psi",
        "percent",
        "temperature_rise",
        "flow_rate",
        "pressure_drop",
        "concentration",
        "pgw",
        "参数",
        "单位",
        "数值",
        "范围",
        "流量",
        "压降",
        "温升",
        "浓度",
    },
    "component": {
        "component",
        "device",
        "part",
        "parts",
        "equipment",
        "gpu",
        "hose",
        "cold_plate",
        "pump",
        "cdu",
        "tim",
        "部件",
        "组成",
        "设备",
        "冷板",
        "泵",
    },
    "fault_case": {
        "abnormal",
        "blockage",
        "contamination",
        "debris",
        "failure",
        "fault",
        "fault_case",
        "leak",
        "leakage",
        "risk",
        "堵塞",
        "失效",
        "异常",
        "故障",
        "泄漏",
        "污染",
    },
}

CATEGORY_HINTS = {
    "concept": {"concept", "coolant", "definition", "liquid_cooling", "meaning", "principle", "role", "是什么", "定义", "概念", "原理"},
    "parameter": {"parameter", "value", "range", "unit", "ratio", "lpm", "kw", "psi", "percent", "参数", "单位", "数值"},
    "component": {"component", "device", "part", "equipment", "gpu", "hose", "cold_plate", "cdu", "tim", "部件", "组成", "设备"},
    "fault_case": {"failure", "fault", "leakage", "leak", "contamination", "abnormal", "blockage", "risk", "故障", "异常", "泄漏", "堵塞", "污染"},
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).lower()).strip()


def _canonical_token(value: str) -> str:
    token = _norm(value)
    token = token.strip(".,;:()[]{}<>!?，。；：！？、 \t\r\n")
    token = token.replace("-", "_").replace("/", "_")
    token = re.sub(r"_+", "_", token)
    return token.strip("_")


def safe_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL identifier: {identifier}")
    return f"`{identifier}`"


def normalize_unit_types(unit_types: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in unit_types or []:
        item = str(value or "").strip().lower()
        if not item or item not in ALLOWED_UNIT_TYPES or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _extract_raw_tokens(query: str) -> list[str]:
    text = str(query or "").strip()
    if not text:
        return []
    raw_terms: list[str] = []
    lowered = text.lower()

    for phrase, aliases in PHRASE_ALIASES.items():
        if phrase in lowered or phrase in text:
            raw_terms.append(phrase)
            raw_terms.extend(aliases)

    for key, aliases in DOMAIN_ALIASES.items():
        if key in lowered or key in text:
            raw_terms.append(key)
            raw_terms.extend(aliases)

    raw_terms.extend(re.findall(r"[A-Za-z0-9_./+\-%]+", lowered))
    raw_terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    raw_terms.extend("".join(cjk_chars[index : index + 2]) for index in range(max(0, len(cjk_chars) - 1)))

    expanded: list[str] = []
    for term in raw_terms:
        cleaned = _canonical_token(term)
        if not cleaned:
            continue
        expanded.append(cleaned)
        expanded.extend(DOMAIN_ALIASES.get(cleaned, ()))

    return [_canonical_token(term) for term in expanded if _canonical_token(term)]


def _unique_terms(terms: list[str], *, max_terms: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        item = _canonical_token(term)
        if len(item) < 2 or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= max_terms:
            break
    return out


def infer_unit_type_hints(tokens: list[str], filtered_tokens: list[str] | None = None) -> list[str]:
    combined = tokens + list(filtered_tokens or [])
    counts: Counter[str] = Counter()
    for token in combined:
        item = normalize_stopword_term(token)
        for unit_type, markers in UNIT_TYPE_INTENT_TERMS.items():
            if item in markers:
                counts[unit_type] += 1

    hints = [unit_type for unit_type, _count in counts.most_common() if unit_type in ALLOWED_UNIT_TYPES]
    if "parameter" in hints and "fault_case" in hints:
        hints = [unit_type for unit_type in hints if unit_type != "mixed"]
    return hints


def infer_category_intent(tokens: list[str], filtered_tokens: list[str] | None = None) -> str:
    combined = [normalize_stopword_term(token) for token in (tokens + list(filtered_tokens or []))]
    counts: Counter[str] = Counter()
    for token in combined:
        for category, markers in CATEGORY_HINTS.items():
            if token in markers:
                counts[category] += 1
    if not counts:
        return "unknown"
    if counts.get("parameter", 0) and counts.get("fault_case", 0):
        return "mixed"
    return counts.most_common(1)[0][0]


def analyze_shadow_query(query: str, *, max_terms: int = 16) -> dict[str, Any]:
    tokens = _unique_terms(_extract_raw_tokens(query), max_terms=max_terms * 2)
    filtered_tokens = _unique_terms(filter_stopwords(tokens), max_terms=max_terms)
    if not filtered_tokens:
        filtered_tokens = [term for term in tokens if not is_stopword(term)][:max_terms]

    unit_type_hints = infer_unit_type_hints(tokens, filtered_tokens)
    category_intent = infer_category_intent(tokens, filtered_tokens)
    match_terms = _unique_terms(filtered_tokens + unit_type_hints, max_terms=max_terms)
    query_debug_info = {
        "raw_query": str(query or ""),
        "tokens": tokens,
        "filtered_tokens": filtered_tokens,
        "removed_stopwords": [term for term in tokens if is_stopword(term)],
        "unit_type_hints": unit_type_hints,
        "category_intent": category_intent,
        "match_terms": match_terms,
        "shadow_only": True,
    }
    return {
        "tokens": tokens,
        "filtered_tokens": filtered_tokens,
        "unit_type_hints": unit_type_hints,
        "match_terms": match_terms,
        "query_debug_info": query_debug_info,
    }


def build_keyword_terms(query: str, *, max_terms: int = 12) -> list[str]:
    return list(analyze_shadow_query(query, max_terms=max_terms).get("match_terms") or [])


def selectable_columns(schema_fields: set[str]) -> list[str]:
    return [column for column in SELECTABLE_COLUMNS if column in schema_fields]


def searchable_columns(schema_fields: set[str]) -> list[str]:
    return [column for column in SEARCHABLE_COLUMNS if column in schema_fields]


def build_where_clause(
    *,
    schema_fields: set[str],
    query_terms: list[str],
    unit_types: list[str] | None = None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []

    filters = normalize_unit_types(unit_types)
    if filters and "unit_type" in schema_fields:
        placeholders = ", ".join(["%s"] * len(filters))
        clauses.append(f"{safe_identifier('unit_type')} IN ({placeholders})")
        params.extend(filters)

    columns = searchable_columns(schema_fields)
    filtered_terms = [term for term in query_terms if term and not is_stopword(term)]
    if filtered_terms and columns:
        like_parts: list[str] = []
        for term in filtered_terms:
            normalized_term = str(term or "").lower().replace("_", " ")
            values = {f"%{str(term).lower()}%", f"%{normalized_term}%"}
            for like_value in sorted(values):
                for column in columns:
                    expression = f"LOWER(CAST({safe_identifier(column)} AS CHAR)) LIKE %s"
                    like_parts.append(expression)
                    params.append(like_value)
        clauses.append("(" + " OR ".join(like_parts) + ")")

    if not clauses:
        return "1 = 0", tuple()
    return " AND ".join(clauses), tuple(params)


def _field_blob(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    return " ".join(_norm(row.get(column)).replace("_", " ") for column in fields)


def _canonical_variants(value: Any) -> set[str]:
    name = _canonical_token(_text(value))
    if not name:
        return set()
    variants = {name, name.replace("_", " ")}
    parts = [part for part in name.split("_") if part]
    if len(parts) > 1:
        variants.add(" ".join(parts))
    return variants


def score_row(
    row: dict[str, Any],
    query_terms: list[str],
    unit_types: list[str] | None = None,
    *,
    unit_type_hints: list[str] | None = None,
) -> tuple[str, float, dict[str, Any]]:
    filters = normalize_unit_types(unit_types)
    hints = normalize_unit_types(unit_type_hints)
    terms = [term for term in query_terms if term and not is_stopword(term)]
    row_type = _canonical_token(row.get("unit_type") or "")
    canonical_name = row.get("canonical_name") or row.get("title")
    canonical_variants = _canonical_variants(canonical_name)
    unit_identity_blob = _field_blob(row, ("unit_code", "dedup_key", "canonical_name", "title"))
    content_blob = _field_blob(row, ("summary", "content", "keywords", "meta_json"))
    all_blob = f"{unit_identity_blob} {content_blob}".strip()

    breakdown: dict[str, Any] = {
        "canonical_exact": 0.0,
        "canonical_partial": 0.0,
        "unit_type_hint": 0.0,
        "unit_type_filter": 0.0,
        "identity_keyword": 0.0,
        "content_keyword": 0.0,
        "multi_token": 0.0,
        "provenance_ready": 0.0,
        "source_warning": 0.0,
        "wrong_unit_type_penalty": 0.0,
        "matched_terms": [],
        "matched_canonical_terms": [],
        "matched_content_terms": [],
        "warnings": [],
    }

    matched_identity: list[str] = []
    matched_content: list[str] = []
    matched_canonical: list[str] = []

    query_joined = " ".join(term.replace("_", " ") for term in terms)
    for variant in canonical_variants:
        canonical_key = variant.replace(" ", "_")
        if variant and (variant in query_joined or canonical_key in terms):
            matched_canonical.append(canonical_key)

    if matched_canonical:
        breakdown["canonical_exact"] = 12.0
    else:
        canonical_parts = set()
        for variant in canonical_variants:
            canonical_parts.update(part for part in variant.replace("_", " ").split() if part)
        part_hits = [term for term in terms if term.replace("_", " ") in canonical_parts or term in canonical_parts]
        if part_hits and len(part_hits) >= min(2, max(1, len(canonical_parts))):
            matched_canonical.extend(part_hits)
            breakdown["canonical_partial"] = min(8.0, 3.0 * len(part_hits))
        elif part_hits:
            matched_canonical.extend(part_hits)
            breakdown["canonical_partial"] = 2.5

    for term in terms:
        term_space = term.replace("_", " ")
        if term in unit_identity_blob or term_space in unit_identity_blob:
            matched_identity.append(term)
        if term in content_blob or term_space in content_blob:
            matched_content.append(term)

    if matched_identity:
        breakdown["identity_keyword"] = min(10.0, 2.5 * len(set(matched_identity)))
    if matched_content:
        breakdown["content_keyword"] = min(5.0, 1.0 * len(set(matched_content)))
    matched_terms = sorted(set(matched_identity + matched_content + matched_canonical))
    if len(matched_terms) > 1:
        breakdown["multi_token"] = min(4.0, 0.75 * len(matched_terms))

    if hints:
        if row_type in hints:
            hint_rank = hints.index(row_type)
            breakdown["unit_type_hint"] = max(2.5, 6.0 - hint_rank)
        else:
            breakdown["wrong_unit_type_penalty"] = -4.0
    if filters:
        breakdown["unit_type_filter"] = 4.0 if row_type in filters else -6.0

    provenance = _norm(row.get("provenance_status"))
    if not provenance:
        meta = _norm(row.get("meta_json"))
        if "ready" in meta:
            provenance = "ready"
    if provenance == "ready":
        breakdown["provenance_ready"] = 0.5

    document_id = row.get("document_id") if row.get("document_id") is not None else row.get("source_doc_id")
    source_chunk_id = row.get("source_chunk_id")
    if document_id in (None, "") or source_chunk_id in (None, ""):
        breakdown["source_warning"] = -1.0
        breakdown["warnings"].append("missing_source_reference")

    breakdown["matched_terms"] = matched_terms[:12]
    breakdown["matched_canonical_terms"] = sorted(set(matched_canonical))[:12]
    breakdown["matched_content_terms"] = sorted(set(matched_content))[:12]

    score = round(
        sum(float(value) for key, value in breakdown.items() if isinstance(value, (int, float)) and key != "warnings"),
        4,
    )
    reason_parts: list[str] = []
    if breakdown["canonical_exact"]:
        reason_parts.append("canonical_exact:" + ",".join(sorted(set(matched_canonical))[:3]))
    elif breakdown["canonical_partial"]:
        reason_parts.append("canonical_partial:" + ",".join(sorted(set(matched_canonical))[:3]))
    if breakdown["unit_type_hint"]:
        reason_parts.append(f"unit_type_hint:{row_type}")
    if matched_terms:
        reason_parts.append("keyword:" + ",".join(matched_terms[:5]))
    if matched_identity:
        reason_parts.append("identity:" + ",".join(sorted(set(matched_identity))[:5]))
    if matched_content:
        reason_parts.append("content:" + ",".join(sorted(set(matched_content))[:5]))
    if breakdown["wrong_unit_type_penalty"]:
        reason_parts.append(f"unit_type_penalty:{row_type}")
    if not reason_parts:
        reason_parts.append("no_keyword_match")
    return ";".join(reason_parts), float(score), breakdown


def build_match_reason(row: dict[str, Any], query_terms: list[str], unit_types: list[str] | None = None) -> tuple[str, float]:
    reason, score, _breakdown = score_row(row, query_terms, unit_types)
    return reason, score


__all__ = [
    "ALLOWED_UNIT_TYPES",
    "DOMAIN_ALIASES",
    "PHRASE_ALIASES",
    "SEARCHABLE_COLUMNS",
    "SELECTABLE_COLUMNS",
    "analyze_shadow_query",
    "build_keyword_terms",
    "build_match_reason",
    "build_where_clause",
    "infer_category_intent",
    "infer_unit_type_hints",
    "normalize_unit_types",
    "safe_identifier",
    "score_row",
    "searchable_columns",
    "selectable_columns",
]
