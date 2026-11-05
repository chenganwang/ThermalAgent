from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from .review_validator import validate_review_record


RUNTIME_DIR = Path("runtime") / "knowledge_unit_candidates"
RUNS_DIR = RUNTIME_DIR / "runs"

DEFAULT_SOURCE_INTAKE_MD = RUNTIME_DIR / "knowledge_unit_source_intake_report.md"
DEFAULT_SOURCE_INTAKE_JSON = RUNTIME_DIR / "knowledge_unit_source_intake_report.json"
DEFAULT_INVENTORY_MD = RUNTIME_DIR / "knowledge_unit_phase2g_inventory_report.md"
DEFAULT_INVENTORY_JSON = RUNTIME_DIR / "knowledge_unit_phase2g_inventory_report.json"
DEFAULT_PHASE2G_ACCEPTED_PACK = RUNTIME_DIR / "batch_accepted_candidates_phase2g.jsonl"
DEFAULT_REVIEW_SHORTLIST = RUNTIME_DIR / "phase2g_review_shortlist.jsonl"
DEFAULT_REVIEW_SHEET = RUNTIME_DIR / "phase2g_review_sheet.md"
DEFAULT_EXPANSION_MD = RUNTIME_DIR / "phase2g_candidate_expansion_report.md"
DEFAULT_EXPANSION_JSON = RUNTIME_DIR / "phase2g_candidate_expansion_report.json"
DEFAULT_WRITE_GATE_MD = RUNTIME_DIR / "phase2g_write_gate_report.md"
DEFAULT_WRITE_GATE_JSON = RUNTIME_DIR / "phase2g_write_gate_report.json"
DEFAULT_SQL_PREVIEW = RUNTIME_DIR / "phase2g_sql_preview.sql"
DEFAULT_NO_WRITE_MD = RUNTIME_DIR / "phase2g_no_write_decision.md"
DEFAULT_NO_WRITE_JSON = RUNTIME_DIR / "phase2g_no_write_decision.json"
DEFAULT_PHASE2G_DB_WRITE_MD = RUNTIME_DIR / "phase2g_db_write_report.md"
DEFAULT_PHASE2G_DB_WRITE_JSON = RUNTIME_DIR / "phase2g_db_write_report.json"
DEFAULT_PHASE2G_DB_SQL_PREVIEW = RUNTIME_DIR / "phase2g_db_write_sql_executed_preview.sql"
DEFAULT_READBACK_MD = RUNTIME_DIR / "phase2g_readback_report.md"
DEFAULT_READBACK_JSON = RUNTIME_DIR / "phase2g_readback_report.json"
DEFAULT_SHADOW_EVAL_MD = RUNTIME_DIR / "phase2g_shadow_evaluation_report.md"
DEFAULT_SHADOW_EVAL_JSON = RUNTIME_DIR / "phase2g_shadow_evaluation_report.json"
DEFAULT_READINESS_MD = RUNTIME_DIR / "phase2g_readiness_decision.md"
DEFAULT_READINESS_JSON = RUNTIME_DIR / "phase2g_readiness_decision.json"

DEFAULT_BATCH_ACCEPTED_INPUT = RUNTIME_DIR / "batch_accepted_candidates_for_writer.jsonl"
DEFAULT_FIXABLE_SHORTLIST = RUNTIME_DIR / "fixable_candidates_shortlist.jsonl"
DEFAULT_REVIEWED_FILE_NAME = "sample_knowledge_unit_review_sheet_reviewed.jsonl"
TARGET_ACCEPTED_COUNT = 50


def _json_default(value: Any) -> str:
    return str(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _write_json(data: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_public_payload(data), ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return output


def _public_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not str(key).startswith("_")}


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in counter.items()))


def load_jsonl_records(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    input_path = Path(path)
    if not input_path.exists():
        return [], [f"missing_file:{input_path}"]
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    with input_path.open("r", encoding="utf-8-sig") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except Exception as exc:
                warnings.append(f"invalid_json_line:{input_path}:{line_no}:{type(exc).__name__}")
                continue
            if isinstance(value, dict):
                records.append(value)
            else:
                warnings.append(f"non_object_line:{input_path}:{line_no}")
    return records, warnings


def write_jsonl_records(records: list[dict[str, Any]], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
    return output


def _record_key(record: dict[str, Any]) -> str:
    return _text(record.get("dedup_key") or record.get("candidate_id") or record.get("id"))


def _is_accepted(record: dict[str, Any]) -> bool:
    return _text(record.get("review_status")) == "accepted"


def _is_needs_review(record: dict[str, Any]) -> bool:
    return _text(record.get("review_status") or record.get("current_review_status")) == "needs_edit"


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": record.get("candidate_id") or record.get("id"),
        "dedup_key": record.get("dedup_key"),
        "unit_type": record.get("unit_type"),
        "canonical_name": record.get("canonical_name"),
        "review_status": record.get("review_status") or record.get("current_review_status"),
        "source_run_name": record.get("source_run_name") or record.get("run_name"),
        "reviewed_file": record.get("reviewed_file") or record.get("source_reviewed_file"),
    }


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = _record_key(record)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _reviewed_run_files(runs_dir: str | Path) -> list[Path]:
    root = Path(runs_dir)
    if not root.exists():
        return []
    return sorted(root.glob(f"*/{DEFAULT_REVIEWED_FILE_NAME}"))


def _jsonl_files(base_dir: str | Path) -> list[Path]:
    root = Path(base_dir)
    if not root.exists():
        return []
    return sorted(root.glob("*.jsonl"))


def _is_phase2g_generated(path: Path) -> bool:
    return path.name.startswith("phase2g_") or path.name == DEFAULT_PHASE2G_ACCEPTED_PACK.name


def _is_review_source_file(path: Path) -> bool:
    name = path.name.lower()
    if "preview" in name or _is_phase2g_generated(path):
        return False
    return "review_sheet" in name or "reviewed" in name


def build_phase2g_inventory_report(
    *,
    base_dir: str | Path = RUNTIME_DIR,
    runs_dir: str | Path = RUNS_DIR,
    current_accepted_pack: str | Path = DEFAULT_BATCH_ACCEPTED_INPUT,
    fixable_shortlist: str | Path = DEFAULT_FIXABLE_SHORTLIST,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
) -> dict[str, Any]:
    base = Path(base_dir)
    jsonl_files = [path for path in _jsonl_files(base) if not _is_phase2g_generated(path)]
    run_reviewed_files = _reviewed_run_files(runs_dir)
    reviewed_files = [
        path
        for path in jsonl_files
        if _is_review_source_file(path)
    ] + run_reviewed_files
    accepted_pack_files = [path for path in jsonl_files if "accepted" in path.name.lower()]
    candidate_files = [path for path in jsonl_files if "candidate" in path.name.lower()]

    loader_warnings: list[str] = []
    current_records, current_warnings = load_jsonl_records(current_accepted_pack)
    loader_warnings.extend(current_warnings)
    current_accepted = _dedupe_records([record for record in current_records if _is_accepted(record)])

    reviewed_records: list[dict[str, Any]] = []
    for path in reviewed_files:
        records, warnings = load_jsonl_records(path)
        loader_warnings.extend(warnings)
        run_name = path.parent.name if path.parent.name != base.name else ""
        for record in records:
            item = dict(record)
            if run_name and "source_run_name" not in item:
                item["source_run_name"] = run_name
            item.setdefault("reviewed_file", str(path))
            reviewed_records.append(item)

    accepted_records: list[dict[str, Any]] = []
    accepted_records.extend(current_accepted)
    accepted_records.extend(record for record in reviewed_records if _is_accepted(record))
    accepted_records = _dedupe_records(accepted_records)
    accepted_keys = {_record_key(record) for record in accepted_records if _record_key(record)}

    needs_review_records = _dedupe_records(
        [record for record in reviewed_records if _is_needs_review(record) and _record_key(record) not in accepted_keys]
    )
    shortlist_records: list[dict[str, Any]] = []
    shortlist_path = Path(fixable_shortlist)
    if shortlist_path.exists():
        shortlist_records, shortlist_warnings = load_jsonl_records(shortlist_path)
        loader_warnings.extend(shortlist_warnings)
        shortlist_records = _dedupe_records(
            [record for record in shortlist_records if _is_needs_review(record) and _record_key(record) not in accepted_keys]
        )

    review_shortlist = shortlist_records or needs_review_records
    counts_by_status = Counter(_text(record.get("review_status") or record.get("current_review_status") or "missing") for record in reviewed_records)
    accepted_count = len(accepted_records)
    needed = max(0, int(target_accepted_count) - accepted_count)
    can_build = accepted_count >= int(target_accepted_count)
    no_write_reason = "" if can_build else "accepted_count_below_target_50_requires_human_review"

    sample_chunks = sorted(Path(runs_dir).glob("*/sample_chunks.json")) if Path(runs_dir).exists() else []
    sample_candidates = sorted(Path(runs_dir).glob("*/sample_knowledge_unit_candidates.jsonl")) if Path(runs_dir).exists() else []

    return {
        "status": "ok",
        "phase": "2G",
        "base_dir": str(base),
        "runs_dir": str(Path(runs_dir)),
        "existing_candidate_files": [str(path) for path in candidate_files],
        "reviewed_candidate_files": [str(path) for path in reviewed_files],
        "accepted_pack_files": [str(path) for path in accepted_pack_files],
        "accepted_count_current": len(current_accepted),
        "accepted_count_after_phase2g": accepted_count,
        "accepted_count_needed_to_50": needed,
        "target_accepted_count": int(target_accepted_count),
        "can_build_phase2g_accepted_pack": can_build,
        "can_write_db_this_round": False,
        "no_write_reason": no_write_reason,
        "counts_by_review_status": _counter_dict(counts_by_status),
        "review_shortlist_count": len(review_shortlist),
        "can_extract_from_existing_chunks": bool(sample_chunks or sample_candidates),
        "existing_sample_chunks_files": [str(path) for path in sample_chunks],
        "existing_candidate_run_files": [str(path) for path in sample_candidates],
        "loader_warnings": loader_warnings[:50],
        "database_written": False,
        "_accepted_records": accepted_records,
        "_needs_review_records": review_shortlist,
    }


def write_source_intake_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_SOURCE_INTAKE_MD,
    report_json: str | Path = DEFAULT_SOURCE_INTAKE_JSON,
) -> dict[str, str]:
    report_json_path = _write_json(data, report_json)
    report_md_path = _write_simple_markdown(
        "Knowledge Unit Source Intake Report",
        data,
        report_md,
        list_keys=("suggested_source_files", "blocked_source_files"),
        boundary_lines=[
            "Source intake lists files and filename-level relevance only.",
            "No OCR, PDF ingestion, chunk rebuild, model call, external API call, or database write is performed.",
        ],
    )
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


def write_inventory_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_INVENTORY_MD,
    report_json: str | Path = DEFAULT_INVENTORY_JSON,
) -> dict[str, str]:
    report_json_path = _write_json(data, report_json)
    report_md_path = _write_simple_markdown(
        "Knowledge Unit Phase 2G Inventory Report",
        data,
        report_md,
        list_keys=("existing_candidate_files", "reviewed_candidate_files", "accepted_pack_files", "existing_sample_chunks_files"),
        boundary_lines=[
            "Inventory reads local JSONL/chunk artifacts only.",
            "Needs-edit candidates remain review-only and are not promoted to accepted by this report.",
        ],
    )
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


def build_candidate_expansion_report(
    inventory: dict[str, Any],
    *,
    provenance_result: dict[str, Any] | None = None,
    accepted_pack_written: bool = False,
    review_package_written: bool = False,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
) -> dict[str, Any]:
    accepted_records = list(inventory.get("_accepted_records") or [])
    needs_review = list(inventory.get("_needs_review_records") or [])
    provenance = provenance_result or {}
    accepted_count = len(accepted_records)
    reached_target = accepted_count >= int(target_accepted_count)
    blocked_reasons: Counter[str] = Counter()
    if not reached_target:
        blocked_reasons["accepted_count_below_target_50"] += int(target_accepted_count) - accepted_count
    if not needs_review and not reached_target:
        blocked_reasons["no_review_shortlist_candidates_found"] += 1

    return {
        "status": "ok",
        "phase": "2G",
        "candidate_count_total": len(accepted_records) + len(needs_review),
        "accepted_count_total": accepted_count,
        "accepted_count_current": int(inventory.get("accepted_count_current") or 0),
        "accepted_count_after_phase2g": accepted_count,
        "newly_added_accepted_count": max(0, accepted_count - int(inventory.get("accepted_count_current") or 0)),
        "needs_review_count": len(needs_review),
        "blocked_count": sum(blocked_reasons.values()),
        "blocked_reasons": _counter_dict(blocked_reasons),
        "provenance_ready_count": int(provenance.get("provenance_ready_count") or 0),
        "provenance_partial_count": int(provenance.get("provenance_partial_count") or 0),
        "provenance_missing_count": int(provenance.get("provenance_missing_count") or 0),
        "target_accepted_count": int(target_accepted_count),
        "reached_target": reached_target,
        "accepted_pack_written": bool(accepted_pack_written),
        "review_package_written": bool(review_package_written),
        "database_written": False,
        "external_api_called": False,
    }


def write_review_package(
    records: list[dict[str, Any]],
    *,
    output_jsonl: str | Path = DEFAULT_REVIEW_SHORTLIST,
    output_md: str | Path = DEFAULT_REVIEW_SHEET,
) -> dict[str, str]:
    shortlist = [dict(record) for record in records if isinstance(record, dict)]
    jsonl_path = write_jsonl_records(shortlist, output_jsonl)
    md_path = Path(output_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 2G Review Sheet",
        "",
        "This package is for human review only. Entries are not promoted to accepted and are not written to the database.",
        "",
        f"- review_candidate_count: {len(shortlist)}",
        "- database_written: false",
        "- external_api_called: false",
        "",
        "| candidate_id | unit_type | canonical_name | current_status | suggested_action | risk | content | source preview |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in shortlist[:120]:
        content = _text(item.get("content"))[:160].replace("|", "\\|")
        source = _text(item.get("source_text_preview"))[:160].replace("|", "\\|")
        lines.append(
            "| {candidate_id} | {unit_type} | {canonical_name} | {status} | {action} | {risk} | {content} | {source} |".format(
                candidate_id=_text(item.get("candidate_id") or item.get("id")),
                unit_type=_text(item.get("unit_type")),
                canonical_name=_text(item.get("canonical_name")).replace("|", "\\|"),
                status=_text(item.get("review_status") or item.get("current_review_status")),
                action=_text(item.get("suggested_action")),
                risk=_text(item.get("risk_level")),
                content=content,
                source=source,
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Human review is required before any entry in this sheet can become review_status=accepted.",
            "- This sheet does not modify reviewed JSONL files and does not write MySQL.",
        ]
    )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"review_shortlist_jsonl": str(jsonl_path), "review_sheet_md": str(md_path)}


def write_expansion_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_EXPANSION_MD,
    report_json: str | Path = DEFAULT_EXPANSION_JSON,
) -> dict[str, str]:
    report_json_path = _write_json(data, report_json)
    report_md_path = _write_simple_markdown(
        "Knowledge Unit Phase 2G Candidate Expansion Report",
        data,
        report_md,
        boundary_lines=[
            "Accepted pack generation is allowed only from existing review_status=accepted records.",
            "Needs-edit shortlist records are review package items only and are not promoted automatically.",
        ],
    )
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


def build_skipped_write_gate_report(*, no_write_reason: str, accepted_count: int, target_accepted_count: int = TARGET_ACCEPTED_COUNT) -> dict[str, Any]:
    return {
        "status": "skipped",
        "phase": "2G",
        "dry_run_executed": False,
        "gate_ready_count": 0,
        "gate_blocked_count": 0,
        "provenance_ready_count": 0,
        "provenance_missing_count": 0,
        "can_write_db": False,
        "accepted_count": int(accepted_count),
        "target_accepted_count": int(target_accepted_count),
        "no_write_reason": no_write_reason,
        "database_written": False,
        "db_connection_opened": False,
        "readonly": True,
    }


def build_write_gate_report(gate_result: dict[str, Any], *, preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    preflight = preflight or {}
    gate_blocked = int(gate_result.get("gate_blocked_count") or 0)
    preflight_valid = bool(preflight.get("valid")) if preflight else gate_blocked == 0
    return {
        "status": gate_result.get("status", "ok"),
        "phase": "2G",
        "dry_run_executed": True,
        "total_candidates": int(gate_result.get("total_candidates") or 0),
        "gate_ready_count": int(gate_result.get("gate_ready_count") or 0),
        "gate_blocked_count": gate_blocked,
        "provenance_ready_count": int(gate_result.get("provenance_ready_count") or 0),
        "provenance_missing_count": int(gate_result.get("provenance_missing_count") or 0),
        "blocking_errors_by_type": gate_result.get("blocking_errors_by_type") or preflight.get("blocking_errors_by_type") or {},
        "warnings_by_type": gate_result.get("warnings_by_type") or preflight.get("warnings_by_type") or {},
        "can_write_db": gate_blocked == 0 and preflight_valid,
        "database_written": False,
        "db_connection_opened": bool(gate_result.get("db_connection_opened")),
        "readonly": True,
        "write_db_required": True,
    }


def write_gate_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_WRITE_GATE_MD,
    report_json: str | Path = DEFAULT_WRITE_GATE_JSON,
    sql_preview: str | Path = DEFAULT_SQL_PREVIEW,
    sql_preview_items: list[Any] | None = None,
) -> dict[str, str]:
    report_json_path = _write_json(data, report_json)
    report_md_path = _write_simple_markdown(
        "Knowledge Unit Phase 2G Write Gate Report",
        data,
        report_md,
        boundary_lines=[
            "This is a dry-run gate report unless a separate explicit --write-db path passes all checks.",
            "No schema migration, index rebuild, OCR, PDF ingest, model call, or external API call is performed.",
        ],
    )
    sql_path = write_sql_preview(data, sql_preview, sql_preview_items=sql_preview_items)
    return {"report_md": str(report_md_path), "report_json": str(report_json_path), "sql_preview": str(sql_path)}


def write_sql_preview(data: dict[str, Any], path: str | Path, *, sql_preview_items: list[Any] | None = None) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- Phase 2G Knowledge Unit SQL Preview",
        "-- Audit preview only; statements are commented out.",
        f"-- database_written={str(bool(data.get('database_written'))).lower()}",
        f"-- can_write_db={str(bool(data.get('can_write_db'))).lower()}",
        "-- No database credentials or connection strings are recorded.",
        "",
    ]
    items = sql_preview_items or []
    if not items:
        lines.append("-- none")
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            sql = _text(item.get("sql_preview") or item.get("sql"))
            candidate_id = _text(item.get("candidate_id"))
        else:
            sql = _text(item)
            candidate_id = ""
        lines.append(f"-- ===== preview {index} {candidate_id} =====")
        for line in sql.splitlines():
            lines.append(f"-- {line}" if line.strip() else "--")
        lines.append("")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def build_no_write_decision(
    *,
    reason: str,
    accepted_count: int,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
    gate_report: dict[str, Any] | None = None,
    write_db_requested: bool = False,
) -> dict[str, Any]:
    return {
        "status": "no_write",
        "phase": "2G",
        "no_write_reason": reason,
        "accepted_count": int(accepted_count),
        "target_accepted_count": int(target_accepted_count),
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


def write_no_write_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_NO_WRITE_MD,
    report_json: str | Path = DEFAULT_NO_WRITE_JSON,
) -> dict[str, str]:
    report_json_path = _write_json(data, report_json)
    report_md_path = _write_simple_markdown(
        "Knowledge Unit Phase 2G No-write Decision",
        data,
        report_md,
        boundary_lines=[
            "Controlled write is blocked until accepted pack and provenance gates pass.",
            "No database write is performed by this decision.",
        ],
    )
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


def build_phase2g_readiness_decision(
    *,
    accepted_count: int,
    evaluation: dict[str, Any],
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
) -> dict[str, Any]:
    p1 = _float_metric(evaluation.get("precision_at_1"))
    p3 = _float_metric(evaluation.get("precision_at_3"))
    unit_type_rate = _float_metric(evaluation.get("unit_type_match_rate"))
    provenance_rate = _float_metric(evaluation.get("provenance_ready_rate"))
    if int(accepted_count) < int(target_accepted_count):
        decision = "need_more_accepted_knowledge_units_before_fusion_policy"
    elif p1 >= 0.65 and p3 >= 0.55 and unit_type_rate >= 0.65 and provenance_rate >= 1.0:
        decision = "ready_for_fusion_policy_dry_run_design"
    else:
        decision = "need_adapter_or_data_quality_improvement"
    return {
        "status": "ok",
        "phase": "2G",
        "accepted_count": int(accepted_count),
        "target_accepted_count": int(target_accepted_count),
        "precision_at_1": p1,
        "precision_at_3": p3,
        "unit_type_match_rate": unit_type_rate,
        "provenance_ready_rate": provenance_rate,
        "readiness_decision": decision,
        "fusion_ready": False,
        "agent_default_dependency": False,
        "default_agent_dependency": False,
        "retrieval_main_path_changed": False,
        "agent_answer_contract_changed": False,
        "database_written": False,
        "external_api_called": False,
        "next_steps": _readiness_next_steps(decision),
    }


def _readiness_next_steps(decision: str) -> list[str]:
    if decision == "ready_for_fusion_policy_dry_run_design":
        return [
            "Enter Phase 2H fusion policy dry-run design only; keep agent default path disabled.",
            "Do not enable formal fusion until a separate dry-run policy is reviewed.",
        ]
    if decision == "need_adapter_or_data_quality_improvement":
        return [
            "Inspect canonical_name, unit_type, and content atomization quality before any fusion design.",
            "Keep knowledge_units shadow-only and do not change the default agent path.",
        ]
    return [
        "Run Phase 2G-1 human review to promote enough shortlist records to accepted.",
        "After accepted_count reaches the target, rerun controlled dry-run, write gate, readback, and shadow evaluation.",
    ]


def _float_metric(value: Any) -> float:
    try:
        return round(float(value), 4)
    except Exception:
        return 0.0


def write_readiness_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_READINESS_MD,
    report_json: str | Path = DEFAULT_READINESS_JSON,
) -> dict[str, str]:
    report_json_path = _write_json(data, report_json)
    report_md_path = _write_simple_markdown(
        "Knowledge Unit Phase 2G Readiness Decision",
        data,
        report_md,
        list_keys=("next_steps",),
        boundary_lines=[
            "fusion_ready remains false in Phase 2G even when dry-run design readiness is met.",
            "The default agent path does not depend on knowledge_units.",
        ],
    )
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


def validate_phase2g_accepted_pack(records: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for record in records:
        if not _is_accepted(record):
            errors.append({"candidate_id": record.get("candidate_id"), "type": "review_status_not_accepted"})
            continue
        validation = validate_review_record(record)
        for issue in validation.get("errors") or []:
            item = dict(issue)
            item.setdefault("type", item.get("error_type", "validation_error"))
            errors.append(item)
        if _text(record.get("provenance_status")) and _text(record.get("provenance_status")) != "ready":
            errors.append({"candidate_id": record.get("candidate_id"), "type": "provenance_status_not_ready"})
    return {"valid": not errors, "errors": errors, "database_written": False}


def _write_simple_markdown(
    title: str,
    data: dict[str, Any],
    path: str | Path,
    *,
    list_keys: tuple[str, ...] = (),
    boundary_lines: list[str] | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    public = _public_payload(data)
    lines = [f"# {title}", "", "## Summary", ""]
    for key in sorted(public):
        if key in list_keys:
            continue
        value = public.get(key)
        if isinstance(value, (dict, list)):
            value_text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)
        else:
            value_text = str(value).lower() if isinstance(value, bool) else str(value)
        lines.append(f"- {key}: {value_text}")

    for key in list_keys:
        lines.extend(["", f"## {key}", ""])
        values = public.get(key) or []
        if isinstance(values, dict):
            values = [{"key": item_key, "value": item_value} for item_key, item_value in values.items()]
        if values:
            iterable = values[:120] if isinstance(values, list) else []
            for item in iterable:
                if isinstance(item, dict):
                    lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
                else:
                    lines.append(f"- {item}")
        else:
            lines.append("- none")

    lines.extend(["", "## Boundary", ""])
    for line in boundary_lines or []:
        lines.append(f"- {line}")
    if not boundary_lines:
        lines.append("- No database credentials or connection strings are written to this report.")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


__all__ = [
    "DEFAULT_BATCH_ACCEPTED_INPUT",
    "DEFAULT_EXPANSION_JSON",
    "DEFAULT_EXPANSION_MD",
    "DEFAULT_INVENTORY_JSON",
    "DEFAULT_INVENTORY_MD",
    "DEFAULT_NO_WRITE_JSON",
    "DEFAULT_NO_WRITE_MD",
    "DEFAULT_PHASE2G_ACCEPTED_PACK",
    "DEFAULT_READBACK_JSON",
    "DEFAULT_READBACK_MD",
    "DEFAULT_READINESS_JSON",
    "DEFAULT_READINESS_MD",
    "DEFAULT_REVIEW_SHEET",
    "DEFAULT_REVIEW_SHORTLIST",
    "DEFAULT_SHADOW_EVAL_JSON",
    "DEFAULT_SHADOW_EVAL_MD",
    "DEFAULT_SOURCE_INTAKE_JSON",
    "DEFAULT_SOURCE_INTAKE_MD",
    "DEFAULT_SQL_PREVIEW",
    "DEFAULT_WRITE_GATE_JSON",
    "DEFAULT_WRITE_GATE_MD",
    "RUNS_DIR",
    "RUNTIME_DIR",
    "TARGET_ACCEPTED_COUNT",
    "build_candidate_expansion_report",
    "build_no_write_decision",
    "build_phase2g_inventory_report",
    "build_phase2g_readiness_decision",
    "build_skipped_write_gate_report",
    "build_write_gate_report",
    "load_jsonl_records",
    "validate_phase2g_accepted_pack",
    "write_expansion_outputs",
    "write_gate_outputs",
    "write_inventory_outputs",
    "write_jsonl_records",
    "write_no_write_outputs",
    "write_readiness_outputs",
    "write_review_package",
    "write_source_intake_outputs",
    "write_sql_preview",
]
