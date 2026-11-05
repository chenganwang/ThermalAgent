from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .quality import VALID_REVIEW_STATUSES

SEVERE_ACCEPTED_FLAGS = {
    "missing_source",
    "content_too_broad",
    "content_contains_multiple_unit_types",
    "thermal_path_order_suspicious",
    "symptom_as_fault_case",
}

_FORMULA_EXPRESSION_RE = re.compile(r"(?:\b[A-Za-z][A-Za-z0-9_]*\b|Δp|ΔT|Rθ)\s*=", re.I)
_PATH_RE = re.compile(r"->|→|鈫|鉃|鈬|\b(?:chip|processor|cold plate|coolant|cdu|it loop|facility loop)\b.+\bto\b", re.I)
_NUMBER_RE = re.compile(r"\d")
_UNIT_RE = re.compile(
    r"(?:°C|℃|\bK\b|\bW\b|\bkW\b|\bPa\b|\bkPa\b|\bMPa\b|\bbar\b|\bpsi\b|L/min|lpm|kg/s|kg/m3|"
    r"J/\(?kg\*?K\)?|J/kgK|W/\(?m\*?K\)?|W/mK|%)",
    re.I,
)
_CONDITION_RE = re.compile(
    r"\b(?:at|under|for|with|ASHRAE|OCP|W17|W27|W32|W40|W45|A[1-4])\b|"
    r"在|下|条件|浓度|工况|乙二醇|丙二醇",
    re.I,
)
_FAULT_HINT_RE = re.compile(
    r"fault|failure|leak|blockage|blocked|insufficient flow|overtemperature|symptom|"
    r"故障|泄漏|堵塞|阻塞|流量不足|过温|温升|症状",
    re.I,
)


def _as_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
    if hasattr(record, "to_dict"):
        try:
            value = record.to_dict()
            return dict(value) if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _properties(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("properties")
    return value if isinstance(value, dict) else {}


def _source(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("source")
    return value if isinstance(value, dict) else {}


def _source_preview(record: dict[str, Any]) -> str:
    return _text(record.get("source_text_preview") or _source(record).get("source_text_preview"))


def _quality_flags(record: dict[str, Any]) -> list[str]:
    flags = record.get("quality_flags")
    if not isinstance(flags, list):
        return []
    return [_text(flag) for flag in flags if _text(flag)]


def _candidate_id(record: dict[str, Any]) -> str:
    return _text(record.get("candidate_id") or record.get("id") or record.get("dedup_key") or "unknown")


def _error(record: dict[str, Any], error_type: str, message: str) -> dict[str, str]:
    return {"candidate_id": _candidate_id(record), "error_type": error_type, "message": message}


def _warning(record: dict[str, Any], warning_type: str, message: str) -> dict[str, str]:
    return {"candidate_id": _candidate_id(record), "warning_type": warning_type, "message": message}


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _field_or_property(record: dict[str, Any], *names: str) -> Any:
    props = _properties(record)
    for name in names:
        if _non_empty(record.get(name)):
            return record.get(name)
        if _non_empty(props.get(name)):
            return props.get(name)
    return None


def _combined_text(record: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            _text(record.get("canonical_name")),
            _text(record.get("title")),
            _text(record.get("content")),
        )
        if part
    )


def _has_formula_expression(record: dict[str, Any]) -> bool:
    explicit = _field_or_property(record, "expression", "formula")
    if _non_empty(explicit):
        return True
    return bool(_FORMULA_EXPRESSION_RE.search(_combined_text(record)))


def _parameter_has_value(record: dict[str, Any]) -> bool:
    value = _field_or_property(record, "value", "values", "range")
    if _non_empty(value):
        return True
    return bool(_NUMBER_RE.search(_combined_text(record)))


def _parameter_has_unit_or_condition(record: dict[str, Any]) -> bool:
    explicit = _field_or_property(record, "unit", "units", "condition", "conditions", "condition_key")
    if _non_empty(explicit):
        return True
    text = _combined_text(record)
    return bool(_UNIT_RE.search(text) or _CONDITION_RE.search(text))


def _has_path_nodes(record: dict[str, Any]) -> bool:
    nodes = _field_or_property(record, "nodes", "path")
    if isinstance(nodes, list) and len([node for node in nodes if _text(node)]) >= 2:
        return True
    if isinstance(nodes, str) and _text(nodes):
        return True
    return bool(_PATH_RE.search(_combined_text(record)))


def _has_fault_name_or_symptom(record: dict[str, Any]) -> bool:
    explicit = _field_or_property(record, "fault_name", "symptom", "symptoms")
    if _non_empty(explicit):
        return True
    canonical = _text(record.get("canonical_name"))
    if canonical and canonical.lower() not in {"unknown", "fault_case", "fault"}:
        return True
    return bool(_FAULT_HINT_RE.search(_combined_text(record)))


def validate_review_record(record: dict) -> dict:
    data = _as_dict(record)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    status = _text(data.get("review_status"))

    if not status:
        warnings.append(_warning(data, "missing_review_status", "review_status is missing; treated as pending for export."))
        status = "pending"
    elif status not in VALID_REVIEW_STATUSES:
        errors.append(_error(data, "invalid_review_status", f"review_status must be one of {sorted(VALID_REVIEW_STATUSES)}."))

    is_accepted = status == "accepted"
    if is_accepted:
        if not _source_preview(data):
            errors.append(_error(data, "accepted_missing_source_text_preview", "accepted candidate must include source_text_preview."))

        severe_flags = sorted(SEVERE_ACCEPTED_FLAGS.intersection(_quality_flags(data)))
        for flag in severe_flags:
            errors.append(_error(data, "accepted_severe_quality_flag", f"accepted candidate contains severe quality flag: {flag}."))

        unit_type = _text(data.get("unit_type"))
        if unit_type == "formula" and not _has_formula_expression(data):
            errors.append(_error(data, "accepted_formula_missing_expression", "accepted formula must include an expression."))
        elif unit_type == "parameter" and _parameter_has_value(data) and not _parameter_has_unit_or_condition(data):
            errors.append(
                _error(
                    data,
                    "accepted_parameter_value_missing_unit_or_condition",
                    "accepted parameter with a value must include unit or condition evidence.",
                )
            )
        elif unit_type == "thermal_path" and not _has_path_nodes(data):
            errors.append(_error(data, "accepted_thermal_path_missing_nodes_or_path", "accepted thermal_path must include nodes/path."))
        elif unit_type == "fault_case" and not _has_fault_name_or_symptom(data):
            errors.append(_error(data, "accepted_fault_case_missing_fault_name_or_symptom", "accepted fault_case must include fault_name or symptom."))

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "review_status": status,
        "accepted": is_accepted,
        "candidate_id": _candidate_id(data),
    }


def validate_reviewed_records(records: list[dict]) -> dict:
    items = [record for record in (records or []) if isinstance(record, dict)]
    counts: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    accepted_with_errors: list[dict[str, Any]] = []
    accepted_count = 0

    for record in items:
        result = validate_review_record(record)
        status = result.get("review_status") or "missing"
        counts[str(status)] += 1
        if result.get("accepted"):
            accepted_count += 1
        record_errors = list(result.get("errors") or [])
        record_warnings = list(result.get("warnings") or [])
        errors.extend(record_errors)
        warnings.extend(record_warnings)
        if result.get("accepted") and record_errors:
            accepted_with_errors.append(
                {
                    "candidate_id": result.get("candidate_id"),
                    "unit_type": record.get("unit_type"),
                    "canonical_name": record.get("canonical_name"),
                    "errors": record_errors,
                }
            )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts_by_review_status": dict(sorted(counts.items())),
        "accepted_count": accepted_count,
        "accepted_with_errors": accepted_with_errors,
    }
