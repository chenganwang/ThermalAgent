from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any

from .phase2g_report import (
    RUNTIME_DIR,
    TARGET_ACCEPTED_COUNT,
    write_jsonl_records,
)
from .review_processor import MIN_WRITE_THRESHOLD


PHASE = "2G-1"

DEFAULT_REVIEW_PACKAGE_INVENTORY_MD = RUNTIME_DIR / "phase2g1_review_package_inventory.md"
DEFAULT_REVIEW_PACKAGE_INVENTORY_JSON = RUNTIME_DIR / "phase2g1_review_package_inventory.json"
DEFAULT_AUTO_REVIEW_SUGGESTIONS_JSONL = RUNTIME_DIR / "phase2g1_auto_review_suggestions.jsonl"
DEFAULT_AUTO_REVIEW_SUGGESTIONS_MD = RUNTIME_DIR / "phase2g1_auto_review_suggestions.md"
DEFAULT_AUTO_REVIEW_REPORT_JSON = RUNTIME_DIR / "phase2g1_auto_review_report.json"
DEFAULT_AUTO_REVIEW_REPORT_MD = RUNTIME_DIR / "phase2g1_auto_review_report.md"
DEFAULT_REVIEWED_CANDIDATES_JSONL = RUNTIME_DIR / "phase2g1_reviewed_candidates_rule_based.jsonl"
DEFAULT_ACCEPTED_PACK_JSONL = RUNTIME_DIR / "batch_accepted_candidates_phase2g1.jsonl"
DEFAULT_ACCEPTED_PACK_REPORT_JSON = RUNTIME_DIR / "phase2g1_accepted_pack_report.json"
DEFAULT_ACCEPTED_PACK_REPORT_MD = RUNTIME_DIR / "phase2g1_accepted_pack_report.md"
DEFAULT_WRITE_GATE_JSON = RUNTIME_DIR / "phase2g1_write_gate_report.json"
DEFAULT_WRITE_GATE_MD = RUNTIME_DIR / "phase2g1_write_gate_report.md"
DEFAULT_SQL_PREVIEW = RUNTIME_DIR / "phase2g1_sql_preview.sql"
DEFAULT_DB_WRITE_JSON = RUNTIME_DIR / "phase2g1_db_write_report.json"
DEFAULT_DB_WRITE_MD = RUNTIME_DIR / "phase2g1_db_write_report.md"
DEFAULT_DB_SQL_PREVIEW = RUNTIME_DIR / "phase2g1_db_write_sql_executed_preview.sql"
DEFAULT_NO_WRITE_JSON = RUNTIME_DIR / "phase2g1_no_write_decision.json"
DEFAULT_NO_WRITE_MD = RUNTIME_DIR / "phase2g1_no_write_decision.md"
DEFAULT_READBACK_JSON = RUNTIME_DIR / "phase2g1_readback_report.json"
DEFAULT_READBACK_MD = RUNTIME_DIR / "phase2g1_readback_report.md"
DEFAULT_SHADOW_EVAL_JSON = RUNTIME_DIR / "phase2g1_shadow_evaluation_report.json"
DEFAULT_SHADOW_EVAL_MD = RUNTIME_DIR / "phase2g1_shadow_evaluation_report.md"
DEFAULT_FINALIZATION_JSON = RUNTIME_DIR / "knowledge_unit_ingestion_finalization_report.json"
DEFAULT_FINALIZATION_MD = RUNTIME_DIR / "knowledge_unit_ingestion_finalization_report.md"
DEFAULT_PAPER_PRELUDE_JSON = RUNTIME_DIR / "paper_ingestion_experiment_prelude.json"
DEFAULT_PAPER_PRELUDE_MD = RUNTIME_DIR / "paper_ingestion_experiment_prelude.md"
DEFAULT_PAPER_METRICS_CSV = RUNTIME_DIR / "paper_ingestion_metrics_table.csv"


def _json_default(value: Any) -> str:
    return str(value)


def _public(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not str(key).startswith("_")}


def _write_json(data: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_public(data), ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return output


def _write_markdown(title: str, data: dict[str, Any], path: str | Path, *, list_keys: tuple[str, ...] = ()) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    public = _public(data)
    lines = [f"# {title}", "", "## Summary", ""]
    for key in sorted(public):
        if key in list_keys:
            continue
        value = public.get(key)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)
        elif isinstance(value, bool):
            value = str(value).lower()
        lines.append(f"- {key}: {value}")

    for key in list_keys:
        lines.extend(["", f"## {key}", ""])
        values = public.get(key) or []
        if isinstance(values, dict):
            values = [{"key": item_key, "value": item_value} for item_key, item_value in values.items()]
        if values:
            for item in list(values)[:120]:
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
            "- Phase 2G-1 processing is deterministic and rule-based.",
            "- No model call, external API call, OCR, PDF batch ingest, index rebuild, fusion, reranker change, or retrieval main path change is performed.",
            "- Controlled database write is allowed only after accepted pack, provenance, dry-run, and write gate all pass; otherwise no-write is recorded.",
            "- Database credentials and connection strings are not written to this report.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def _count_review_status(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        counts[str(record.get("review_status") or "missing")] += 1
    return dict(sorted(counts.items()))


def write_review_package_inventory_outputs(data: dict[str, Any]) -> dict[str, str]:
    json_path = _write_json(data, DEFAULT_REVIEW_PACKAGE_INVENTORY_JSON)
    md_path = _write_markdown(
        "Phase 2G-1 Review Package Inventory",
        data,
        DEFAULT_REVIEW_PACKAGE_INVENTORY_MD,
        list_keys=("discovered_review_files", "missing_files", "loader_warnings"),
    )
    return {"report_json": str(json_path), "report_md": str(md_path)}


def write_auto_review_outputs(report: dict[str, Any], suggestions: list[dict[str, Any]]) -> dict[str, str]:
    suggestions_jsonl = write_jsonl_records(suggestions, DEFAULT_AUTO_REVIEW_SUGGESTIONS_JSONL)
    suggestions_md = _write_suggestions_markdown(suggestions, DEFAULT_AUTO_REVIEW_SUGGESTIONS_MD)
    json_path = _write_json(report, DEFAULT_AUTO_REVIEW_REPORT_JSON)
    md_path = _write_markdown(
        "Phase 2G-1 Auto Review Report",
        report,
        DEFAULT_AUTO_REVIEW_REPORT_MD,
        list_keys=("blocked_reasons",),
    )
    return {
        "suggestions_jsonl": str(suggestions_jsonl),
        "suggestions_md": str(suggestions_md),
        "report_json": str(json_path),
        "report_md": str(md_path),
    }


def _write_suggestions_markdown(suggestions: list[dict[str, Any]], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 2G-1 Auto Review Suggestions",
        "",
        "| candidate_id | classification | unit_type | canonical_name | review_method | blockers |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in suggestions:
        blockers = ", ".join(str(value) for value in item.get("strict_blockers") or [])[:260].replace("|", "\\|")
        lines.append(
            "| {candidate_id} | {classification} | {unit_type} | {canonical_name} | {method} | {blockers} |".format(
                candidate_id=str(item.get("candidate_id") or ""),
                classification=str(item.get("auto_review_classification") or ""),
                unit_type=str(item.get("unit_type") or ""),
                canonical_name=str(item.get("canonical_name") or "").replace("|", "\\|"),
                method=str(item.get("review_method") or ""),
                blockers=blockers,
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- auto_acceptable means deterministic strict-rule acceptance only, not human review.",
            "- needs_human_review records remain blocked from the accepted pack.",
            "- human_review_faked is false for every generated suggestion.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_reviewed_candidates_outputs(records: list[dict[str, Any]]) -> dict[str, str]:
    path = write_jsonl_records(records, DEFAULT_REVIEWED_CANDIDATES_JSONL)
    return {"reviewed_candidates_jsonl": str(path)}


def write_accepted_pack_outputs(report: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, str]:
    pack_path = write_jsonl_records(records, DEFAULT_ACCEPTED_PACK_JSONL)
    data = dict(report)
    data["accepted_pack_path"] = str(pack_path)
    data["counts_by_review_status"] = _count_review_status(records)
    json_path = _write_json(data, DEFAULT_ACCEPTED_PACK_REPORT_JSON)
    md_path = _write_markdown("Phase 2G-1 Accepted Pack Report", data, DEFAULT_ACCEPTED_PACK_REPORT_MD)
    return {"accepted_pack": str(pack_path), "report_json": str(json_path), "report_md": str(md_path)}


def build_skipped_write_gate_report(
    *,
    reason: str,
    accepted_count: int,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "phase": PHASE,
        "dry_run": True,
        "dry_run_executed": False,
        "skip_reason": reason,
        "gate_ready_count": 0,
        "gate_blocked_count": 0,
        "provenance_ready_count": 0,
        "provenance_missing_count": 0,
        "duplicate_count": 0,
        "can_write_db": False,
        "accepted_count_after_phase2g1": int(accepted_count),
        "target_accepted_count": int(target_accepted_count),
        "minimum_write_threshold": MIN_WRITE_THRESHOLD,
        "database_written": False,
        "db_connection_opened": False,
        "readonly": True,
    }


def build_write_gate_report(gate_result: dict[str, Any], *, validation: dict[str, Any] | None = None) -> dict[str, Any]:
    validation = validation or {"valid": True, "errors": []}
    gate_blocked = int(gate_result.get("gate_blocked_count") or 0)
    duplicate_count = int(gate_result.get("duplicate_count") or 0)
    can_write = gate_blocked == 0 and bool(validation.get("valid")) and int(gate_result.get("total_candidates") or 0) >= MIN_WRITE_THRESHOLD
    return {
        "status": gate_result.get("status", "ok"),
        "phase": PHASE,
        "dry_run": True,
        "dry_run_executed": True,
        "total_candidates": int(gate_result.get("total_candidates") or 0),
        "gate_ready_count": int(gate_result.get("gate_ready_count") or 0),
        "gate_blocked_count": gate_blocked,
        "provenance_ready_count": int(gate_result.get("provenance_ready_count") or 0),
        "provenance_missing_count": int(gate_result.get("provenance_missing_count") or 0),
        "duplicate_count": duplicate_count,
        "blocking_errors_by_type": gate_result.get("blocking_errors_by_type") or {},
        "warnings_by_type": gate_result.get("warnings_by_type") or {},
        "accepted_pack_validation_errors": validation.get("errors") or [],
        "can_write_db": bool(can_write),
        "database_written": False,
        "db_connection_opened": bool(gate_result.get("db_connection_opened")),
        "readonly": True,
    }


def write_write_gate_outputs(data: dict[str, Any], sql_preview_items: list[dict[str, Any]] | None = None) -> dict[str, str]:
    json_path = _write_json(data, DEFAULT_WRITE_GATE_JSON)
    md_path = _write_markdown("Phase 2G-1 Write Gate Report", data, DEFAULT_WRITE_GATE_MD)
    sql_path = write_sql_preview(data, DEFAULT_SQL_PREVIEW, sql_preview_items=sql_preview_items or [])
    return {"report_json": str(json_path), "report_md": str(md_path), "sql_preview": str(sql_path)}


def write_sql_preview(data: dict[str, Any], path: str | Path, *, sql_preview_items: list[dict[str, Any]]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- Phase 2G-1 Knowledge Unit SQL Preview",
        "-- Audit preview only; statements are commented out.",
        f"-- database_written={str(bool(data.get('database_written'))).lower()}",
        f"-- can_write_db={str(bool(data.get('can_write_db'))).lower()}",
        "-- No database credentials or connection strings are recorded.",
        "",
    ]
    if not sql_preview_items:
        lines.append("-- none")
    for index, item in enumerate(sql_preview_items, start=1):
        lines.append(f"-- ===== preview {index} {item.get('candidate_id', '')} =====")
        for line in str(item.get("sql_preview") or "").splitlines():
            lines.append(f"-- {line}" if line.strip() else "--")
        lines.append("")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def build_no_write_decision(
    *,
    reason: str,
    accepted_count: int,
    gate_report: dict[str, Any] | None = None,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
    write_db_requested: bool = False,
) -> dict[str, Any]:
    return {
        "status": "no_write",
        "phase": PHASE,
        "no_write_reason": reason,
        "accepted_count_after_phase2g1": int(accepted_count),
        "target_accepted_count": int(target_accepted_count),
        "minimum_write_threshold": MIN_WRITE_THRESHOLD,
        "write_db_requested": bool(write_db_requested),
        "gate_can_write_db": bool((gate_report or {}).get("can_write_db")),
        "database_written": False,
        "db_connection_opened": False,
        "committed": False,
        "rolled_back": False,
        "inserted_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "verified_count": 0,
        "missing_after_write": [],
        "core_fields_match": False,
    }


def write_no_write_outputs(data: dict[str, Any]) -> dict[str, str]:
    json_path = _write_json(data, DEFAULT_NO_WRITE_JSON)
    md_path = _write_markdown("Phase 2G-1 No-write Decision", data, DEFAULT_NO_WRITE_MD)
    return {"report_json": str(json_path), "report_md": str(md_path)}


def build_finalization_report(
    *,
    accepted_count_current: int,
    accepted_count_after_phase2g1: int,
    write_executed: bool,
    readback: dict[str, Any],
    shadow_evaluation: dict[str, Any],
    contract_tests_status: str,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
) -> dict[str, Any]:
    readback_ok = (
        str(readback.get("status")) == "ok"
        and int(readback.get("missing_count") or 0) == 0
        and int(readback.get("field_mismatch_count") or 0) == 0
    )
    shadow_ok = str(shadow_evaluation.get("status")) == "ok"
    provenance_ready_rate = _float(shadow_evaluation.get("provenance_ready_rate"))
    p1 = _float(shadow_evaluation.get("precision_at_1"))
    unit_type_rate = _float(shadow_evaluation.get("unit_type_match_rate"))
    tests_ok = contract_tests_status == "passed"
    demo_ready = (
        int(accepted_count_after_phase2g1) >= MIN_WRITE_THRESHOLD
        and readback_ok
        and provenance_ready_rate >= 1.0
        and tests_ok
        and p1 >= 0.65
        and unit_type_rate >= 0.65
    )
    remaining_gaps: list[str] = []
    if int(accepted_count_after_phase2g1) < MIN_WRITE_THRESHOLD:
        remaining_gaps.append("accepted_count_below_minimum_demo_threshold_20")
    if int(accepted_count_after_phase2g1) < int(target_accepted_count):
        remaining_gaps.append("accepted_count_below_target_50")
    if not readback_ok:
        remaining_gaps.append("readback_not_clean")
    if not tests_ok:
        remaining_gaps.append("contract_tests_not_confirmed_passed")
    if p1 < 0.65 or unit_type_rate < 0.65:
        remaining_gaps.append("shadow_quality_below_demo_threshold")
    return {
        "phase": PHASE,
        "status": "ok",
        "accepted_count_current": int(accepted_count_current),
        "accepted_count_after_phase2g1": int(accepted_count_after_phase2g1),
        "target_accepted_count": int(target_accepted_count),
        "write_executed": bool(write_executed),
        "readback_status": "ok" if readback_ok else "needs_attention",
        "shadow_evaluation_status": "ok" if shadow_ok else "needs_attention",
        "provenance_ready_rate": provenance_ready_rate,
        "contract_tests_status": contract_tests_status,
        "minimum_demo_ready": bool(demo_ready),
        "ingestion_pipeline_code_ready": bool(demo_ready),
        "production_ready": False,
        "remaining_gaps": remaining_gaps,
        "next_required_action": _next_required_action(int(accepted_count_after_phase2g1), readback_ok, tests_ok),
        "fusion_ready": False,
        "default_agent_dependency": False,
        "agent_default_dependency": False,
        "retrieval_main_path_changed": False,
        "agent_answer_contract_changed": False,
        "database_written": False,
        "external_api_called": False,
    }


def _next_required_action(accepted_count: int, readback_ok: bool, tests_ok: bool) -> str:
    if not readback_ok or not tests_ok:
        return "fix_readback_or_contract_regression_before_expansion"
    if accepted_count < MIN_WRITE_THRESHOLD:
        return "phase2g1b_human_review_remaining_candidates_or_expand_extraction"
    if accepted_count < TARGET_ACCEPTED_COUNT:
        return "phase2g2_continue_candidate_generation_and_human_review_to_50"
    return "phase2h_fusion_policy_dry_run_design_only"


def write_finalization_outputs(data: dict[str, Any]) -> dict[str, str]:
    json_path = _write_json(data, DEFAULT_FINALIZATION_JSON)
    md_path = _write_markdown("Knowledge Unit Ingestion Finalization Report", data, DEFAULT_FINALIZATION_MD, list_keys=("remaining_gaps",))
    return {"report_json": str(json_path), "report_md": str(md_path)}


def build_paper_prelude(
    *,
    inventory: dict[str, Any],
    auto_review: dict[str, Any],
    accepted_pack: dict[str, Any],
    no_write_reason: str,
    gate_report: dict[str, Any],
    readback: dict[str, Any],
    shadow_evaluation: dict[str, Any],
) -> dict[str, Any]:
    expected = int(readback.get("expected_count") or 0)
    field_match = int(readback.get("field_match_count") or 0)
    return {
        "status": "ok",
        "phase": PHASE,
        "paper_topic": "Traceable Knowledge Unit Ingestion for Retrieval-Augmented Engineering Agents",
        "pipeline_phases_summary": [
            "Phase 1: extraction/review scaffolding",
            "Phase 2B: controlled writer",
            "Phase 2C: readback validation",
            "Phase 2D: optional shadow retrieval adapter",
            "Phase 2E: shadow quality evaluation",
            "Phase 2F: precision improvement",
            "Phase 2G: source intake and review package generation",
            "Phase 2G-1: strict rule-based review package processing",
        ],
        "candidate_count": int(auto_review.get("input_needs_edit_count") or 0) + int(accepted_pack.get("accepted_count_before") or 0),
        "accepted_count": int(accepted_pack.get("accepted_count_after_phase2g1") or 0),
        "needs_edit_count": int(auto_review.get("input_needs_edit_count") or 0),
        "auto_acceptable_count": int(auto_review.get("auto_acceptable_count") or 0),
        "rejected_suggested_count": int(auto_review.get("reject_suggested_count") or 0),
        "duplicate_suggested_count": int(auto_review.get("duplicate_suggested_count") or 0),
        "provenance_ready_rate": _float(shadow_evaluation.get("provenance_ready_rate")),
        "readback_match_rate": round(field_match / expected, 4) if expected else 0.0,
        "shadow_precision_at_1": _float(shadow_evaluation.get("precision_at_1")),
        "shadow_precision_at_3": _float(shadow_evaluation.get("precision_at_3")),
        "unit_type_match_rate": _float(shadow_evaluation.get("unit_type_match_rate")),
        "no_write_decisions": [no_write_reason] if no_write_reason else [],
        "gate_decisions": {
            "dry_run_executed": bool(gate_report.get("dry_run_executed")),
            "can_write_db": bool(gate_report.get("can_write_db")),
            "gate_ready_count": int(gate_report.get("gate_ready_count") or 0),
            "gate_blocked_count": int(gate_report.get("gate_blocked_count") or 0),
        },
        "controlled_write_count": 0 if no_write_reason else 1,
        "remaining_gaps_for_paper": [
            "small accepted knowledge_units sample",
            "human review still required for blocked needs_edit records",
            "fusion policy remains untested",
            "larger corpus scale is needed before production claims",
        ],
        "suggested_next_experiments": [
            "Human review of remaining needs_human_review candidates.",
            "Expand accepted knowledge_units to at least 50 and rerun readback plus shadow evaluation.",
            "Design a dry-run fusion policy after data scale and quality gates pass.",
        ],
        "database_written": False,
        "external_api_called": False,
        "fusion_ready": False,
    }


def write_paper_prelude_outputs(data: dict[str, Any]) -> dict[str, str]:
    json_path = _write_json(data, DEFAULT_PAPER_PRELUDE_JSON)
    md_path = _write_markdown(
        "Paper Ingestion Experiment Prelude",
        data,
        DEFAULT_PAPER_PRELUDE_MD,
        list_keys=("pipeline_phases_summary", "no_write_decisions", "remaining_gaps_for_paper", "suggested_next_experiments"),
    )
    csv_path = _write_metrics_csv(data, DEFAULT_PAPER_METRICS_CSV)
    return {"report_json": str(json_path), "report_md": str(md_path), "metrics_csv": str(csv_path)}


def _write_metrics_csv(data: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("phase", data.get("phase")),
        ("candidate_count", data.get("candidate_count")),
        ("accepted_count", data.get("accepted_count")),
        ("needs_edit_count", data.get("needs_edit_count")),
        ("auto_acceptable_count", data.get("auto_acceptable_count")),
        ("rejected_suggested_count", data.get("rejected_suggested_count")),
        ("duplicate_suggested_count", data.get("duplicate_suggested_count")),
        ("provenance_ready_rate", data.get("provenance_ready_rate")),
        ("readback_match_rate", data.get("readback_match_rate")),
        ("shadow_precision_at_1", data.get("shadow_precision_at_1")),
        ("shadow_precision_at_3", data.get("shadow_precision_at_3")),
        ("unit_type_match_rate", data.get("unit_type_match_rate")),
        ("controlled_write_count", data.get("controlled_write_count")),
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerows(rows)
    return output


def _float(value: Any) -> float:
    try:
        return round(float(value), 4)
    except Exception:
        return 0.0


__all__ = [
    "DEFAULT_ACCEPTED_PACK_JSONL",
    "DEFAULT_AUTO_REVIEW_REPORT_JSON",
    "DEFAULT_AUTO_REVIEW_REPORT_MD",
    "DEFAULT_AUTO_REVIEW_SUGGESTIONS_JSONL",
    "DEFAULT_FINALIZATION_JSON",
    "DEFAULT_FINALIZATION_MD",
    "DEFAULT_NO_WRITE_JSON",
    "DEFAULT_NO_WRITE_MD",
    "DEFAULT_PAPER_METRICS_CSV",
    "DEFAULT_PAPER_PRELUDE_JSON",
    "DEFAULT_PAPER_PRELUDE_MD",
    "DEFAULT_READBACK_JSON",
    "DEFAULT_READBACK_MD",
    "DEFAULT_SHADOW_EVAL_JSON",
    "DEFAULT_SHADOW_EVAL_MD",
    "MIN_WRITE_THRESHOLD",
    "PHASE",
    "build_finalization_report",
    "build_no_write_decision",
    "build_paper_prelude",
    "build_skipped_write_gate_report",
    "build_write_gate_report",
    "write_accepted_pack_outputs",
    "write_auto_review_outputs",
    "write_finalization_outputs",
    "write_no_write_outputs",
    "write_paper_prelude_outputs",
    "write_review_package_inventory_outputs",
    "write_reviewed_candidates_outputs",
    "write_write_gate_outputs",
]
