from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_REVIEW_SHEET = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_review_sheet.jsonl"
DEFAULT_REVIEW_REPORT = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_review_report.md"


def _flags(record: dict) -> list[str]:
    flags = record.get("quality_flags")
    return flags if isinstance(flags, list) else []


def write_review_report(records: list[dict], path: str) -> Path:
    items = list(records or [])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    by_unit_type = Counter(record.get("unit_type") or "unknown" for record in items)
    by_quality = Counter(record.get("quality_level") or "unknown" for record in items)
    by_recommended = Counter(record.get("recommended_review_status") or "unknown" for record in items)
    by_review = Counter(record.get("review_status") or "unknown" for record in items)
    average = sum(float(record.get("quality_score") or 0.0) for record in items) / len(items) if items else 0.0

    missing_source_count = sum(1 for record in items if "missing_source" in _flags(record) or not record.get("source_text_preview"))
    duplicate_like_count = sum(1 for record in items if "duplicate_like" in _flags(record) or record.get("recommended_review_status") == "duplicate")
    formula_missing_variables_count = sum(1 for record in items if "formula_missing_variables" in _flags(record))
    parameter_missing_unit_count = sum(1 for record in items if "parameter_missing_unit" in _flags(record))
    content_too_broad_count = sum(1 for record in items if "content_too_broad" in _flags(record))
    content_contains_multiple_unit_types_count = sum(1 for record in items if "content_contains_multiple_unit_types" in _flags(record))
    thermal_path_order_suspicious_count = sum(1 for record in items if "thermal_path_order_suspicious" in _flags(record))
    parameter_value_missing_count = sum(1 for record in items if "parameter_value_missing" in _flags(record))
    symptom_as_fault_case_count = sum(1 for record in items if "symptom_as_fault_case" in _flags(record))
    thermal_path_without_path_evidence_count = sum(1 for record in items if "thermal_path_without_path_evidence" in _flags(record))
    parameter_without_value_or_range_count = sum(1 for record in items if "parameter_without_value_or_range" in _flags(record))
    standard_range_misclassified_count = sum(1 for record in items if "standard_range_misclassified" in _flags(record))
    requirement_sentence_not_knowledge_unit_count = sum(1 for record in items if "requirement_sentence_not_knowledge_unit" in _flags(record))
    weak_accepted_candidate_count = sum(1 for record in items if "weak_accepted_candidate" in _flags(record))

    grouped_low: dict[str, list[dict]] = defaultdict(list)
    for record in sorted(items, key=lambda item: float(item.get("quality_score") or 0.0)):
        if record.get("quality_level") == "low":
            grouped_low[record.get("unit_type") or "unknown"].append(record)
    accepted_examples = [
        record for record in sorted(items, key=lambda item: float(item.get("quality_score") or 0.0), reverse=True)
        if record.get("recommended_review_status") == "accepted"
    ][:10]
    blocked_flags = {
        "thermal_path_without_path_evidence",
        "parameter_without_value_or_range",
        "standard_range_misclassified",
        "requirement_sentence_not_knowledge_unit",
        "weak_accepted_candidate",
    }
    blocked_examples = [record for record in items if blocked_flags.intersection(_flags(record))][:10]

    lines = [
        "# Knowledge Unit Candidate Review Report",
        "",
        "## Summary",
        "",
        f"- total_candidates: {len(items)}",
        f"- counts_by_unit_type: {json.dumps(dict(sorted(by_unit_type.items())), ensure_ascii=False, sort_keys=True)}",
        f"- counts_by_quality_level: {json.dumps(dict(sorted(by_quality.items())), ensure_ascii=False, sort_keys=True)}",
        f"- counts_by_recommended_review_status: {json.dumps(dict(sorted(by_recommended.items())), ensure_ascii=False, sort_keys=True)}",
        f"- counts_by_review_status: {json.dumps(dict(sorted(by_review.items())), ensure_ascii=False, sort_keys=True)}",
        f"- average_quality_score: {average:.3f}",
        f"- missing_source_count: {missing_source_count}",
        f"- duplicate_like_count: {duplicate_like_count}",
        f"- formula_missing_variables_count: {formula_missing_variables_count}",
        f"- parameter_missing_unit_count: {parameter_missing_unit_count}",
        f"- content_too_broad_count: {content_too_broad_count}",
        f"- content_contains_multiple_unit_types_count: {content_contains_multiple_unit_types_count}",
        f"- thermal_path_order_suspicious_count: {thermal_path_order_suspicious_count}",
        f"- parameter_value_missing_count: {parameter_value_missing_count}",
        f"- symptom_as_fault_case_count: {symptom_as_fault_case_count}",
        f"- thermal_path_without_path_evidence_count: {thermal_path_without_path_evidence_count}",
        f"- parameter_without_value_or_range_count: {parameter_without_value_or_range_count}",
        f"- standard_range_misclassified_count: {standard_range_misclassified_count}",
        f"- requirement_sentence_not_knowledge_unit_count: {requirement_sentence_not_knowledge_unit_count}",
        f"- weak_accepted_candidate_count: {weak_accepted_candidate_count}",
        "",
        "## Low Quality Examples",
        "",
    ]

    low_examples = [record for records in grouped_low.values() for record in records][:10]
    if not low_examples:
        lines.append("- none")
    else:
        for record in low_examples:
            flags = ", ".join(_flags(record)) or "none"
            lines.append(
                f"- {record.get('candidate_id')} | {record.get('unit_type')} | "
                f"score={float(record.get('quality_score') or 0.0):.3f} | flags={flags}"
            )

    lines.extend(["", "## Recommended Accepted Examples", ""])
    if not accepted_examples:
        lines.append("- none")
    else:
        for record in accepted_examples:
            flags = ", ".join(_flags(record)) or "none"
            lines.append(
                f"- {record.get('candidate_id')} | {record.get('unit_type')} | "
                f"score={float(record.get('quality_score') or 0.0):.3f} | flags={flags} | title={record.get('title')}"
            )

    lines.extend(["", "## Blocked Examples", ""])
    if not blocked_examples:
        lines.append("- none")
    else:
        for record in blocked_examples:
            flags = ", ".join(_flags(record)) or "none"
            lines.append(
                f"- {record.get('candidate_id')} | {record.get('unit_type')} | "
                f"recommended={record.get('recommended_review_status')} | flags={flags}"
            )

    lines.extend(
        [
            "",
            "## Recommendations",
            "",
            "- Accept only reviewed records with review_status=accepted for any future writer phase.",
            "- Inspect needs_edit records before editing canonical_name, content, properties, or source trace.",
            "- Keep rejected and duplicate records in the review sheet for auditability; do not delete source candidates.",
            "- Do not write candidates to MySQL until Phase 2 writer.py and upsert safeguards are implemented.",
        ]
    )

    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output
