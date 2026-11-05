from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any

from .contracts import VALID_UNIT_TYPES

MAIN_TARGET_TABLE = "knowledge_units"

EXTENSION_TABLE_BY_UNIT_TYPE = {
    "formula": "formulas",
    "component": "components",
    "thermal_path": "thermal_paths",
    "fault_case": "fault_cases",
}

UNIT_TYPE_TARGET_TABLE = {
    "concept": MAIN_TARGET_TABLE,
    "parameter": MAIN_TARGET_TABLE,
    "formula": MAIN_TARGET_TABLE,
    "component": MAIN_TARGET_TABLE,
    "thermal_path": MAIN_TARGET_TABLE,
    "fault_case": MAIN_TARGET_TABLE,
}

PROPERTY_FIELD_NAMES = (
    "parameter_type",
    "parameter_name",
    "value",
    "values",
    "range",
    "unit",
    "units",
    "condition",
    "conditions",
    "property_type",
    "expression",
    "formula",
    "variables",
    "nodes",
    "path",
    "edges",
    "role",
    "connected_to",
    "risks",
    "fault_name",
    "symptom",
    "possible_causes",
    "affected_components",
    "mitigation",
)


def _json_default(value: Any) -> str:
    return str(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _source(candidate: dict[str, Any]) -> dict[str, Any]:
    value = candidate.get("source")
    return value if isinstance(value, dict) else {}


def _properties(candidate: dict[str, Any]) -> dict[str, Any]:
    properties = candidate.get("properties")
    result = dict(properties) if isinstance(properties, dict) else {}
    for name in PROPERTY_FIELD_NAMES:
        if name in candidate and candidate.get(name) not in (None, "", [], {}):
            result.setdefault(name, candidate.get(name))
    return result


def _first_present(candidate: dict[str, Any], source: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if candidate.get(name) not in (None, ""):
            return candidate.get(name)
        if source.get(name) not in (None, ""):
            return source.get(name)
    return None


def _candidate_id(candidate: dict[str, Any]) -> str:
    existing = _text(candidate.get("candidate_id") or candidate.get("id"))
    if existing:
        return existing
    payload = json.dumps(
        {
            "dedup_key": candidate.get("dedup_key"),
            "unit_type": candidate.get("unit_type"),
            "canonical_name": candidate.get("canonical_name"),
            "content": candidate.get("content"),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=_json_default,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"ku_writer_{digest[:16]}"


def _issue(candidate_id: str, issue_type: str, message: str) -> dict[str, str]:
    return {"candidate_id": candidate_id, "type": issue_type, "message": message}


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _sql_string(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    return _sql_string(value)


def _json_literal(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)
    return f"CAST({_sql_string(text)} AS JSON)"


def _sql_number_or_null(value: Any) -> str:
    parsed = _int_or_none(value)
    return str(parsed) if parsed is not None else "NULL"


def _stable_code(raw: str, *, prefix: str, max_len: int = 128) -> str:
    base = re.sub(r"[^0-9A-Za-z_]+", "_", _text(raw).lower()).strip("_")
    if not base:
        base = prefix
    if len(base) <= max_len:
        return base
    digest = hashlib.sha1(_text(raw).encode("utf-8")).hexdigest()[:16]
    keep = max(1, max_len - len(digest) - 1)
    return f"{base[:keep].rstrip('_')}_{digest}"


def _title(candidate: dict[str, Any], canonical_name: str) -> str:
    return _text(candidate.get("title")) or canonical_name or _text(candidate.get("dedup_key")) or "untitled knowledge unit"


def _source_text_preview(candidate: dict[str, Any], source: dict[str, Any]) -> str:
    return _text(candidate.get("source_text_preview") or source.get("source_text_preview"))


def _keywords(candidate: dict[str, Any], canonical_name: str) -> list[str]:
    values: list[str] = []
    for value in (canonical_name, candidate.get("title")):
        text = _text(value)
        if text and text not in values:
            values.append(text)
    aliases = candidate.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            text = _text(alias)
            if text and text not in values:
                values.append(text)
    return values[:12]


def _meta_json(
    candidate: dict[str, Any],
    *,
    candidate_id: str,
    dedup_key: str,
    properties: dict[str, Any],
    source_text_preview: str,
) -> dict[str, Any]:
    meta = {
        "candidate_id": candidate_id,
        "dedup_key": dedup_key,
        "writer_phase": "phase_2a_dry_run",
        "source_text_preview": source_text_preview,
        "source_asset_id": candidate.get("source_asset_id"),
        "review_status": candidate.get("review_status"),
        "recommended_review_status": candidate.get("recommended_review_status"),
        "quality_flags": candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else [],
        "source_run_name": candidate.get("source_run_name"),
        "reviewed_file": candidate.get("reviewed_file"),
        "reviewer_note": candidate.get("reviewer_note"),
        "provenance_status": candidate.get("provenance_status"),
        "provenance_warnings": candidate.get("provenance_warnings"),
        "provenance_backfill_method": candidate.get("provenance_backfill_method"),
        "properties": properties,
    }
    aliases = candidate.get("aliases")
    if isinstance(aliases, list):
        meta["aliases"] = aliases
    return {key: value for key, value in meta.items() if value not in (None, "", [], {})}


def _knowledge_units_sql(plan: dict[str, Any]) -> str:
    meta = plan["metadata_preview"]
    title = plan["title"]
    unit_code = plan["unit_code"]
    confidence = plan.get("confidence")
    return "\n".join(
        [
            "-- DRY-RUN PREVIEW ONLY: not executed by Phase 2A",
            "INSERT INTO knowledge_units",
            "  (unit_code, unit_type, title, summary, content, source_doc_id, source_chunk_id, keywords, confidence_score, review_status, meta_json)",
            "VALUES",
            "  ("
            + ", ".join(
                [
                    _sql_literal(unit_code),
                    _sql_literal(plan["unit_type"]),
                    _sql_literal(title),
                    _sql_literal(plan["content"][:512]),
                    _sql_literal(plan["content"]),
                    _sql_number_or_null(plan.get("document_id")),
                    _sql_number_or_null(plan.get("source_chunk_id")),
                    _json_literal(plan.get("keywords") or []),
                    _sql_literal(float(confidence) if confidence not in (None, "") else 0.0),
                    _sql_literal("reviewed"),
                    _json_literal(meta),
                ]
            )
            + ")",
            "ON DUPLICATE KEY UPDATE",
            "  title = VALUES(title),",
            "  summary = VALUES(summary),",
            "  content = VALUES(content),",
            "  source_doc_id = COALESCE(VALUES(source_doc_id), source_doc_id),",
            "  source_chunk_id = COALESCE(VALUES(source_chunk_id), source_chunk_id),",
            "  keywords = VALUES(keywords),",
            "  confidence_score = VALUES(confidence_score),",
            "  review_status = VALUES(review_status),",
            "  meta_json = VALUES(meta_json),",
            "  updated_at = CURRENT_TIMESTAMP;",
        ]
    )


def _formula_expression(candidate: dict[str, Any], properties: dict[str, Any], content: str) -> str:
    explicit = _text(properties.get("expression") or properties.get("formula"))
    if explicit:
        return explicit
    combined = " ".join(part for part in (_text(candidate.get("title")), content) if part)
    if "=" in combined:
        return combined[:1024]
    return ""


def _path_nodes(properties: dict[str, Any], content: str) -> list[str]:
    nodes = properties.get("nodes") or properties.get("path")
    if isinstance(nodes, list):
        return [_text(node) for node in nodes if _text(node)]
    if isinstance(nodes, str) and nodes.strip():
        parts = re.split(r"\s*(?:->|=>|鈫抾閳珅閴億閳瑋|→|/|,)\s*", nodes)
        return [_text(part) for part in parts if _text(part)]
    if "->" in content or "→" in content:
        parts = re.split(r"\s*(?:->|→)\s*", content)
        return [_text(part) for part in parts if _text(part)][:12]
    return []


def _extension_sql(plan: dict[str, Any], candidate: dict[str, Any], properties: dict[str, Any]) -> str:
    table = plan.get("extension_table")
    if not table:
        return ""
    doc_id = _sql_number_or_null(plan.get("document_id"))
    chunk_id = _sql_number_or_null(plan.get("source_chunk_id"))
    meta = _json_literal(plan["metadata_preview"])
    code = _stable_code(plan["dedup_key"], prefix=table.rstrip("s"))

    if table == "formulas":
        expression = _formula_expression(candidate, properties, plan["content"])
        return "\n".join(
            [
                "-- DRY-RUN PREVIEW ONLY: formula extension preview",
                "INSERT INTO formulas",
                "  (formula_code, name, expression, description, variables, units, required_inputs, optional_inputs, output_variables, applicable_conditions, source_doc_id, source_chunk_id, meta_json)",
                "VALUES",
                "  ("
                + ", ".join(
                    [
                        _sql_literal(code),
                        _sql_literal(plan["canonical_name"] or plan["title"]),
                        _sql_literal(expression),
                        _sql_literal(plan["content"]),
                        _json_literal(properties.get("variables") if isinstance(properties.get("variables"), dict) else {}),
                        _json_literal(properties.get("units") or {}),
                        _json_literal(properties.get("required_inputs") or []),
                        _json_literal(properties.get("optional_inputs") or []),
                        _json_literal(properties.get("output_variables") or []),
                        _sql_literal(_text(properties.get("condition") or properties.get("conditions")) or None),
                        doc_id,
                        chunk_id,
                        meta,
                    ]
                )
                + ")",
                "ON DUPLICATE KEY UPDATE expression = VALUES(expression), description = VALUES(description), variables = VALUES(variables), units = VALUES(units), meta_json = VALUES(meta_json), updated_at = CURRENT_TIMESTAMP;",
            ]
        )

    if table == "components":
        return "\n".join(
            [
                "-- DRY-RUN PREVIEW ONLY: component extension preview",
                "INSERT INTO components",
                "  (component_code, name, category, function_desc, key_parameters, typical_failure_modes, source_doc_id, source_chunk_id, meta_json)",
                "VALUES",
                "  ("
                + ", ".join(
                    [
                        _sql_literal(code),
                        _sql_literal(plan["canonical_name"] or plan["title"]),
                        _sql_literal(_text(properties.get("category") or properties.get("component_type")) or None),
                        _sql_literal(plan["content"]),
                        _json_literal(properties),
                        _json_literal(properties.get("risks") or properties.get("typical_failure_modes") or []),
                        doc_id,
                        chunk_id,
                        meta,
                    ]
                )
                + ")",
                "ON DUPLICATE KEY UPDATE name = VALUES(name), function_desc = VALUES(function_desc), key_parameters = VALUES(key_parameters), typical_failure_modes = VALUES(typical_failure_modes), meta_json = VALUES(meta_json), updated_at = CURRENT_TIMESTAMP;",
            ]
        )

    if table == "thermal_paths":
        nodes = _path_nodes(properties, plan["content"])
        edges = properties.get("edges") if isinstance(properties.get("edges"), list) else []
        edge_types = properties.get("edge_types") or edges
        return "\n".join(
            [
                "-- DRY-RUN PREVIEW ONLY: thermal_path extension preview",
                "INSERT INTO thermal_paths",
                "  (path_code, name, scenario, node_sequence, edge_types, description, source_doc_id, source_chunk_id, meta_json)",
                "VALUES",
                "  ("
                + ", ".join(
                    [
                        _sql_literal(code),
                        _sql_literal(plan["canonical_name"] or plan["title"]),
                        _sql_literal(_text(properties.get("scenario")) or None),
                        _json_literal(nodes),
                        _json_literal(edge_types or []),
                        _sql_literal(plan["content"]),
                        doc_id,
                        chunk_id,
                        meta,
                    ]
                )
                + ")",
                "ON DUPLICATE KEY UPDATE name = VALUES(name), node_sequence = VALUES(node_sequence), edge_types = VALUES(edge_types), description = VALUES(description), meta_json = VALUES(meta_json), updated_at = CURRENT_TIMESTAMP;",
            ]
        )

    if table == "fault_cases":
        symptom = _text(properties.get("symptom")) or plan["content"] or plan["canonical_name"]
        return "\n".join(
            [
                "-- DRY-RUN PREVIEW ONLY: fault_case extension preview",
                "INSERT INTO fault_cases",
                "  (fault_code, symptom, fault_category, related_parameters, possible_causes, reasoning_chain, check_suggestions, related_component_ids, related_path_ids, source_doc_id, source_chunk_id, meta_json)",
                "VALUES",
                "  ("
                + ", ".join(
                    [
                        _sql_literal(code),
                        _sql_literal(symptom[:512]),
                        _sql_literal(_text(properties.get("fault_category") or properties.get("fault_name")) or None),
                        _json_literal(properties.get("related_parameters") or []),
                        _json_literal(properties.get("possible_causes") or []),
                        _json_literal(properties.get("reasoning_chain") or []),
                        _json_literal(properties.get("mitigation") or properties.get("check_suggestions") or []),
                        _json_literal(properties.get("affected_components") or properties.get("related_component_ids") or []),
                        _json_literal(properties.get("related_path_ids") or []),
                        doc_id,
                        chunk_id,
                        meta,
                    ]
                )
                + ")",
                "ON DUPLICATE KEY UPDATE symptom = VALUES(symptom), fault_category = VALUES(fault_category), possible_causes = VALUES(possible_causes), check_suggestions = VALUES(check_suggestions), meta_json = VALUES(meta_json), updated_at = CURRENT_TIMESTAMP;",
            ]
        )

    return ""


def _validate_extension_fields(
    plan: dict[str, Any],
    candidate: dict[str, Any],
    properties: dict[str, Any],
    blocking_errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    candidate_id = plan["candidate_id"]
    unit_type = plan["unit_type"]
    content = plan["content"]

    if unit_type == "formula" and not _formula_expression(candidate, properties, content):
        blocking_errors.append(
            _issue(candidate_id, "formula_missing_expression_for_extension", "formula extension preview requires an expression.")
        )
    elif unit_type == "thermal_path" and len(_path_nodes(properties, content)) < 2:
        blocking_errors.append(
            _issue(candidate_id, "thermal_path_missing_nodes_for_extension", "thermal_path extension preview requires at least two path nodes.")
        )
    elif unit_type == "component" and not properties:
        warnings.append(_issue(candidate_id, "component_extension_properties_empty", "component preview has no structured properties."))
    elif unit_type == "fault_case" and not (_text(properties.get("symptom")) or content or plan["canonical_name"]):
        blocking_errors.append(_issue(candidate_id, "fault_case_missing_symptom_for_extension", "fault_case extension preview requires a symptom."))


def map_candidate_to_write_plan(candidate: dict) -> dict:
    data = dict(candidate or {}) if isinstance(candidate, dict) else {}
    source = _source(data)
    candidate_id = _candidate_id(data)
    unit_type = _text(data.get("unit_type"))
    canonical_name = _text(data.get("canonical_name"))
    content = _text(data.get("content"))
    dedup_key = _text(data.get("dedup_key"))
    properties = _properties(data)
    document_id = _first_present(data, source, ("document_id", "doc_id", "source_doc_id", "source_document_id"))
    source_chunk_id = _first_present(data, source, ("source_chunk_id", "chunk_id"))
    source_asset_id = _first_present(data, source, ("source_asset_id", "asset_id", "source_file"))
    source_text_preview = _source_text_preview(data, source)
    title = _title(data, canonical_name)

    blocking_errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if unit_type not in VALID_UNIT_TYPES:
        blocking_errors.append(_issue(candidate_id, "invalid_unit_type", f"unsupported unit_type: {unit_type or '<missing>'}"))
    if not canonical_name:
        blocking_errors.append(_issue(candidate_id, "missing_canonical_name", "canonical_name is required for knowledge_units.title/code mapping."))
    if not content:
        blocking_errors.append(_issue(candidate_id, "missing_content", "content is required for knowledge_units.content mapping."))
    if not dedup_key:
        blocking_errors.append(_issue(candidate_id, "missing_dedup_key", "dedup_key is required for upsert identity."))
    if not source_text_preview:
        blocking_errors.append(_issue(candidate_id, "missing_source_text_preview", "source_text_preview is required as dry-run source support."))

    if document_id in (None, ""):
        warnings.append(_issue(candidate_id, "missing_document_id", "document_id/source_doc_id is missing; preview will use NULL source_doc_id."))
    elif _int_or_none(document_id) is None:
        warnings.append(_issue(candidate_id, "document_id_not_integer", "document_id is present but not an integer; preview will use NULL source_doc_id."))

    if source_chunk_id in (None, ""):
        warnings.append(_issue(candidate_id, "missing_source_chunk_id", "source_chunk_id/chunk_id is missing; preview will use NULL source_chunk_id."))
    elif _int_or_none(source_chunk_id) is None:
        warnings.append(
            _issue(candidate_id, "source_chunk_id_not_integer", "source_chunk_id/chunk_id is present but not an integer; preview will use NULL source_chunk_id.")
        )

    if not properties:
        warnings.append(_issue(candidate_id, "missing_properties", "properties is empty; only generic knowledge_units mapping can be verified."))

    extension_table = EXTENSION_TABLE_BY_UNIT_TYPE.get(unit_type)
    if extension_table:
        warnings.append(
            _issue(
                candidate_id,
                "extension_table_preview_only",
                f"{extension_table} mapping is preview-only in Phase 2A and will not be written.",
            )
        )

    unit_code = _stable_code(dedup_key or f"{unit_type}:{canonical_name}", prefix="ku")
    meta = _meta_json(
        data,
        candidate_id=candidate_id,
        dedup_key=dedup_key,
        properties=properties,
        source_text_preview=source_text_preview,
    )

    plan: dict[str, Any] = {
        "candidate_id": candidate_id,
        "unit_type": unit_type,
        "canonical_name": canonical_name,
        "title": title,
        "target_table": UNIT_TYPE_TARGET_TABLE.get(unit_type, MAIN_TARGET_TABLE),
        "extension_table": extension_table,
        "extension_table_supported": bool(extension_table),
        "extension_table_preview_only": bool(extension_table),
        "dedup_key": dedup_key,
        "unit_code": unit_code,
        "source_chunk_id": source_chunk_id,
        "document_id": document_id,
        "source_asset_id": source_asset_id,
        "source_run_name": data.get("source_run_name"),
        "provenance_status": data.get("provenance_status"),
        "provenance_warnings": data.get("provenance_warnings") if isinstance(data.get("provenance_warnings"), list) else [],
        "provenance_backfill_method": data.get("provenance_backfill_method"),
        "source_text_preview": source_text_preview,
        "content": content,
        "properties": properties,
        "keywords": _keywords(data, canonical_name),
        "confidence": data.get("confidence"),
        "metadata_preview": meta,
        "sql_preview": [],
        "can_write": False,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
    }

    _validate_extension_fields(plan, data, properties, blocking_errors, warnings)
    plan["sql_preview"] = [_knowledge_units_sql(plan)]
    extension_sql = _extension_sql(plan, data, properties)
    if extension_sql:
        plan["sql_preview"].append(extension_sql)
    plan["can_write"] = not blocking_errors
    return plan


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in counter.items()))


def _issue_counts(plans: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for plan in plans:
        for item in plan.get(field) or []:
            counter[str(item.get("type") or "unknown")] += 1
    return _counter_dict(counter)


def map_candidates_to_write_plan(candidates: list[dict]) -> dict:
    plans = [map_candidate_to_write_plan(candidate) for candidate in candidates or [] if isinstance(candidate, dict)]

    dedup_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for plan in plans:
        dedup_key = _text(plan.get("dedup_key"))
        if dedup_key:
            dedup_groups[dedup_key].append(plan)

    duplicate_dedup_keys: dict[str, list[str]] = {}
    for dedup_key, group in dedup_groups.items():
        if len(group) <= 1:
            continue
        duplicate_dedup_keys[dedup_key] = [str(plan.get("candidate_id")) for plan in group]
        group[0]["warnings"].append(
            _issue(
                str(group[0].get("candidate_id")),
                "duplicate_dedup_key_primary",
                "Duplicate dedup_key found in this batch; first occurrence is kept as the write-ready preview.",
            )
        )
        for duplicate in group[1:]:
            duplicate["blocking_errors"].append(
                _issue(
                    str(duplicate.get("candidate_id")),
                    "duplicate_dedup_key",
                    "Duplicate dedup_key found in this batch; later occurrences are blocked to avoid ambiguous upsert order.",
                )
            )
            duplicate["can_write"] = False

    counts_by_unit_type = Counter(plan.get("unit_type") or "unknown" for plan in plans)
    target_table_counts: Counter[str] = Counter()
    for plan in plans:
        if plan.get("target_table"):
            target_table_counts[str(plan["target_table"])] += 1
        if plan.get("extension_table"):
            target_table_counts[str(plan["extension_table"])] += 1

    write_ready_count = sum(1 for plan in plans if plan.get("can_write"))
    blocked_count = len(plans) - write_ready_count
    duplicate_record_count = sum(max(0, len(group) - 1) for group in dedup_groups.values())

    return {
        "status": "ok",
        "total_candidates": len(plans),
        "write_plans": plans,
        "write_ready_count": write_ready_count,
        "blocked_count": blocked_count,
        "counts_by_unit_type": _counter_dict(counts_by_unit_type),
        "target_table_counts": _counter_dict(target_table_counts),
        "duplicate_dedup_key_count": duplicate_record_count,
        "duplicate_dedup_keys": duplicate_dedup_keys,
        "blocking_errors_by_type": _issue_counts(plans, "blocking_errors"),
        "warnings_by_type": _issue_counts(plans, "warnings"),
        "dedup_strategy": "dedup_key maps to knowledge_units.unit_code; first duplicate remains write-ready, later duplicates are blocked in the same batch.",
        "unit_type_target_strategy": dict(UNIT_TYPE_TARGET_TABLE),
        "extension_table_strategy": dict(EXTENSION_TABLE_BY_UNIT_TYPE),
        "extension_table_supported": True,
        "extension_table_preview_only": True,
        "database_written": False,
        "can_enter_phase2b": blocked_count == 0,
    }
