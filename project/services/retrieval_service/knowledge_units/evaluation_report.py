from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_EVALUATION_REPORT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_evaluation_report.md"
DEFAULT_EVALUATION_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_evaluation_report.json"
DEFAULT_FALSE_POSITIVE_ANALYSIS_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_false_positive_analysis.md"
DEFAULT_FALSE_POSITIVE_ANALYSIS_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_false_positive_analysis.json"
DEFAULT_PRECISION_IMPROVEMENT_REPORT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_precision_improvement_report.md"
DEFAULT_PRECISION_IMPROVEMENT_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_precision_improvement_report.json"


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(data: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    return output


def write_evaluation_report_json(data: dict[str, Any], path: str | Path = DEFAULT_EVALUATION_REPORT_JSON) -> Path:
    return _write_json(data, path)


def _summary_line(data: dict[str, Any], key: str, default: Any = 0) -> str:
    return f"- {key}: {data.get(key, default)}"


def write_evaluation_report_markdown(data: dict[str, Any], path: str | Path = DEFAULT_EVALUATION_REPORT_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Knowledge Unit Shadow Retrieval Quality Evaluation",
        "",
        "## Summary",
        "",
        _summary_line(data, "status", "unknown"),
        _summary_line(data, "query_count"),
        _summary_line(data, "hit_query_count"),
        _summary_line(data, "miss_query_count"),
        _summary_line(data, "total_hit_count"),
        _summary_line(data, "useful_hit_count"),
        _summary_line(data, "partial_hit_count"),
        _summary_line(data, "wrong_hit_count"),
        _summary_line(data, "unjudged_hit_count"),
        _summary_line(data, "precision_at_1", 0.0),
        _summary_line(data, "precision_at_3", 0.0),
        _summary_line(data, "unit_type_match_rate", 0.0),
        _summary_line(data, "provenance_ready_rate", 0.0),
        _summary_line(data, "current_precision_at_1", data.get("precision_at_1", 0.0)),
        _summary_line(data, "current_precision_at_3", data.get("precision_at_3", 0.0)),
        _summary_line(data, "current_unit_type_match_rate", data.get("unit_type_match_rate", 0.0)),
        _summary_line(data, "current_provenance_ready_rate", data.get("provenance_ready_rate", 0.0)),
        _summary_line(data, "delta_precision_at_1", 0.0),
        _summary_line(data, "delta_precision_at_3", 0.0),
        _summary_line(data, "delta_unit_type_match_rate", 0.0),
        _summary_line(data, "delta_provenance_ready_rate", 0.0),
        _summary_line(data, "readiness_decision", data.get("readiness_decision", "not_evaluated")),
        f"- fusion_ready: {str(bool(data.get('fusion_ready'))).lower()}",
        f"- counts_by_unit_type: {json.dumps(data.get('counts_by_unit_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- counts_by_query_category: {json.dumps(data.get('counts_by_query_category') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- database_written: {str(bool(data.get('database_written'))).lower()}",
        f"- readonly: {str(bool(data.get('readonly'))).lower()}",
        f"- default_agent_dependency: {str(bool(data.get('default_agent_dependency'))).lower()}",
        f"- fusion_enabled: {str(bool(data.get('fusion_enabled'))).lower()}",
        f"- external_api_called: {str(bool(data.get('external_api_called'))).lower()}",
        f"- unit_type_filter_enabled: {str(bool(data.get('unit_type_filter_enabled'))).lower()}",
        f"- top_k: {data.get('top_k')}",
        "",
        "## Query Results",
        "",
    ]

    for item in data.get("query_results") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "- "
            + json.dumps(
                {
                    "query_id": item.get("query_id"),
                    "category": item.get("category"),
                    "difficulty": item.get("difficulty"),
                    "hit_count": item.get("hit_count"),
                    "top1_judgment": item.get("top1_judgment"),
                    "useful_hit_count": item.get("useful_hit_count"),
                    "partial_hit_count": item.get("partial_hit_count"),
                    "wrong_hit_count": item.get("wrong_hit_count"),
                    "top_hits": item.get("top_hits") or [],
                },
                ensure_ascii=False,
                sort_keys=True,
                default=_json_default,
            )
        )

    lines.extend(["", "## False Positive Examples", ""])
    false_positive_examples = data.get("false_positive_examples") or []
    if false_positive_examples:
        for item in false_positive_examples[:10]:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Miss Examples", ""])
    miss_examples = data.get("miss_examples") or []
    if miss_examples:
        for item in miss_examples[:10]:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Errors", ""])
    error_examples = data.get("error_examples") or []
    if error_examples:
        for item in error_examples[:10]:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Next Steps", ""])
    for step in data.get("next_steps") or []:
        lines.append(f"- {step}")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This report evaluates optional knowledge_units shadow retrieval quality only.",
            "- The evaluation executes adapter SELECT-only retrieval when explicitly enabled by the script.",
            "- No INSERT, UPDATE, DELETE, ALTER, DROP, OCR, PDF ingest, index rebuild, model call, external API call, fusion, reranker change, or retrieval_service main-chain change is performed.",
            "- knowledge_units does not replace chunk retrieval in this phase.",
            "- The default agent and /agent/answer contract do not depend on knowledge_units.",
            "- Database credentials and connection strings are not printed or written to this report.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_evaluation_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_EVALUATION_REPORT_MD,
    report_json: str | Path = DEFAULT_EVALUATION_REPORT_JSON,
) -> dict[str, str]:
    report_json_path = write_evaluation_report_json(data, report_json)
    report_md_path = write_evaluation_report_markdown(data, report_md)
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


def write_false_positive_analysis_json(
    data: dict[str, Any],
    path: str | Path = DEFAULT_FALSE_POSITIVE_ANALYSIS_JSON,
) -> Path:
    return _write_json(data, path)


def write_false_positive_analysis_markdown(
    data: dict[str, Any],
    path: str | Path = DEFAULT_FALSE_POSITIVE_ANALYSIS_MD,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = data.get("summary") or {}
    lines = [
        "# Knowledge Unit Shadow False Positive Analysis",
        "",
        "## Summary",
        "",
        _summary_line(data, "phase", "2F"),
        _summary_line(data, "status", "unknown"),
        f"- baseline_metrics: {json.dumps(data.get('baseline_metrics') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- top1_wrong_or_partial_count: {summary.get('top1_wrong_or_partial_count', 0)}",
        f"- false_positive_unit_types: {json.dumps(summary.get('false_positive_unit_types') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- generic_term_matches: {json.dumps(summary.get('generic_term_matches') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- content_field_overwide: {str(bool(summary.get('content_field_overwide'))).lower()}",
        f"- canonical_name_hit_insufficient_count: {summary.get('canonical_name_hit_insufficient_count', 0)}",
        f"- expected_unit_type_mismatch_count: {summary.get('expected_unit_type_mismatch_count', 0)}",
        f"- query_category_type_mismatch_count: {summary.get('query_category_type_mismatch_count', 0)}",
        f"- database_written: {str(bool(data.get('database_written'))).lower()}",
        f"- readonly: {str(bool(data.get('readonly'))).lower()}",
        f"- external_api_called: {str(bool(data.get('external_api_called'))).lower()}",
        f"- default_agent_dependency: {str(bool(data.get('default_agent_dependency'))).lower()}",
        f"- fusion_ready: {str(bool(data.get('fusion_ready'))).lower()}",
        "",
        "## Top1 Wrong Or Partial Queries",
        "",
    ]
    for item in data.get("top1_wrong_or_partial_queries") or []:
        lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    if not data.get("top1_wrong_or_partial_queries"):
        lines.append("- none")

    sections = [
        ("Content Overwide Examples", "content_overwide_examples"),
        ("Canonical Name Hit Insufficient", "canonical_name_hit_insufficient"),
        ("Expected Type Mismatches", "expected_type_mismatches"),
        ("Query Category Type Mismatches", "query_category_type_mismatches"),
    ]
    for title, key in sections:
        lines.extend(["", f"## {title}", ""])
        values = data.get(key) or []
        if values:
            for item in values:
                lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
        else:
            lines.append("- none")

    lines.extend(["", "## Analysis Notes", ""])
    for note in data.get("analysis_notes") or []:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This analysis reads the Phase 2E report only and performs no database writes.",
            "- No model call, external API call, fusion, reranker, index rebuild, OCR, or retrieval main path change is performed.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_false_positive_analysis_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_FALSE_POSITIVE_ANALYSIS_MD,
    report_json: str | Path = DEFAULT_FALSE_POSITIVE_ANALYSIS_JSON,
) -> dict[str, str]:
    report_json_path = write_false_positive_analysis_json(data, report_json)
    report_md_path = write_false_positive_analysis_markdown(data, report_md)
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


def write_precision_improvement_report_json(
    data: dict[str, Any],
    path: str | Path = DEFAULT_PRECISION_IMPROVEMENT_REPORT_JSON,
) -> Path:
    return _write_json(data, path)


def write_precision_improvement_report_markdown(
    data: dict[str, Any],
    path: str | Path = DEFAULT_PRECISION_IMPROVEMENT_REPORT_MD,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Knowledge Unit Shadow Precision Improvement Report",
        "",
        "## Summary",
        "",
        _summary_line(data, "phase", "2F"),
        _summary_line(data, "status", "unknown"),
        _summary_line(data, "goal", ""),
        f"- baseline_metrics: {json.dumps(data.get('baseline_metrics') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- current_metrics: {json.dumps(data.get('current_metrics') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- metric_delta: {json.dumps(data.get('metric_delta') or {}, ensure_ascii=False, sort_keys=True)}",
        _summary_line(data, "precision_at_1", 0.0),
        _summary_line(data, "precision_at_3", 0.0),
        _summary_line(data, "unit_type_match_rate", 0.0),
        _summary_line(data, "provenance_ready_rate", 0.0),
        _summary_line(data, "current_precision_at_1", 0.0),
        _summary_line(data, "current_precision_at_3", 0.0),
        _summary_line(data, "current_unit_type_match_rate", 0.0),
        _summary_line(data, "current_provenance_ready_rate", 0.0),
        _summary_line(data, "delta_precision_at_1", 0.0),
        _summary_line(data, "delta_precision_at_3", 0.0),
        _summary_line(data, "delta_unit_type_match_rate", 0.0),
        _summary_line(data, "delta_provenance_ready_rate", 0.0),
        _summary_line(data, "readiness_decision", "unknown"),
        f"- fusion_ready: {str(bool(data.get('fusion_ready'))).lower()}",
        f"- database_written: {str(bool(data.get('database_written'))).lower()}",
        f"- readonly: {str(bool(data.get('readonly'))).lower()}",
        f"- external_api_called: {str(bool(data.get('external_api_called'))).lower()}",
        f"- default_agent_dependency: {str(bool(data.get('default_agent_dependency'))).lower()}",
        f"- retrieval_main_path_changed: {str(bool(data.get('retrieval_main_path_changed'))).lower()}",
        f"- agent_answer_contract_changed: {str(bool(data.get('agent_answer_contract_changed'))).lower()}",
        "",
        "## False Positive Analysis Summary",
        "",
        f"- {json.dumps(data.get('false_positive_analysis_summary') or {}, ensure_ascii=False, sort_keys=True)}",
    ]
    sections = [
        ("Scoring Changes", "scoring_changes"),
        ("Query Builder Changes", "query_builder_changes"),
        ("Stopword Filtering Changes", "stopword_filtering_changes"),
        ("Examples Improved", "examples_improved"),
        ("Examples Still Wrong", "examples_still_wrong"),
        ("Next Steps", "next_steps"),
    ]
    for title, key in sections:
        lines.extend(["", f"## {title}", ""])
        values = data.get(key) or []
        if values:
            for item in values:
                if isinstance(item, dict):
                    lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
                else:
                    lines.append(f"- {item}")
        else:
            lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Phase 2F remains shadow/evaluation only.",
            "- The knowledge_units adapter remains optional, read-only, default disabled, and not used by the default agent path.",
            "- No INSERT, UPDATE, DELETE, schema change, index rebuild, OCR, PDF ingest, model call, external API call, formal fusion, or formal reranker is performed.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_precision_improvement_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_PRECISION_IMPROVEMENT_REPORT_MD,
    report_json: str | Path = DEFAULT_PRECISION_IMPROVEMENT_REPORT_JSON,
) -> dict[str, str]:
    report_json_path = write_precision_improvement_report_json(data, report_json)
    report_md_path = write_precision_improvement_report_markdown(data, report_md)
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


__all__ = [
    "DEFAULT_EVALUATION_REPORT_JSON",
    "DEFAULT_EVALUATION_REPORT_MD",
    "DEFAULT_FALSE_POSITIVE_ANALYSIS_JSON",
    "DEFAULT_FALSE_POSITIVE_ANALYSIS_MD",
    "DEFAULT_PRECISION_IMPROVEMENT_REPORT_JSON",
    "DEFAULT_PRECISION_IMPROVEMENT_REPORT_MD",
    "write_evaluation_outputs",
    "write_evaluation_report_json",
    "write_evaluation_report_markdown",
    "write_false_positive_analysis_outputs",
    "write_false_positive_analysis_json",
    "write_false_positive_analysis_markdown",
    "write_precision_improvement_outputs",
    "write_precision_improvement_report_json",
    "write_precision_improvement_report_markdown",
]
