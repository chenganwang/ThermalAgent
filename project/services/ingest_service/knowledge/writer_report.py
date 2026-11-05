from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_WRITER_REPORT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_writer_dry_run_report.md"
DEFAULT_WRITER_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_writer_dry_run_report.json"
DEFAULT_WRITER_SQL_PREVIEW = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_writer_sql_preview.sql"
DEFAULT_WRITER_GATE_REPORT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_writer_gate_dry_run_report.md"
DEFAULT_WRITER_GATE_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_writer_gate_dry_run_report.json"
DEFAULT_WRITER_GATE_SQL_PREVIEW = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_writer_gate_sql_preview.sql"


def _json_default(value: Any) -> str:
    return str(value)


def _short_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": plan.get("candidate_id"),
        "unit_type": plan.get("unit_type"),
        "canonical_name": plan.get("canonical_name"),
        "target_table": plan.get("target_table"),
        "extension_table": plan.get("extension_table"),
        "dedup_key": plan.get("dedup_key"),
        "source_chunk_id": plan.get("source_chunk_id"),
        "document_id": plan.get("document_id"),
        "source_asset_id": plan.get("source_asset_id"),
        "source_run_name": plan.get("source_run_name"),
        "provenance_status": plan.get("provenance_status"),
        "provenance_backfill_method": plan.get("provenance_backfill_method"),
        "can_write": bool(plan.get("can_write")),
        "gate_can_write": bool(plan.get("gate_can_write")) if "gate_can_write" in plan else None,
        "blocking_errors": plan.get("blocking_errors") or [],
        "warnings": plan.get("warnings") or [],
        "gate_blocking_errors": plan.get("gate_blocking_errors") or [],
        "gate_warnings": plan.get("gate_warnings") or [],
    }


def _sql_examples(plans: list[dict[str, Any]], limit: int = 3) -> list[str]:
    examples: list[str] = []
    for plan in plans:
        for sql in plan.get("sql_preview") or []:
            if sql:
                examples.append(str(sql))
            if len(examples) >= limit:
                return examples
    return examples


def _next_steps(result: dict[str, Any]) -> list[str]:
    blocked_count = int(result.get("blocked_count") or 0)
    warnings_by_type = result.get("warnings_by_type") or {}
    steps = [
        "Keep this writer phase in dry-run mode; do not execute the preview SQL.",
        "Review target_table_counts and extension previews before enabling any future write-db switch.",
    ]
    if blocked_count:
        steps.append("Fix blocking_errors in reviewed source files, rerun batch acceptance, then rerun writer dry-run.")
    else:
        steps.append("No blocking writer mapping errors were found in this dry-run batch.")
    if warnings_by_type.get("missing_document_id") or warnings_by_type.get("missing_source_chunk_id"):
        steps.append("Backfill document_id/source_chunk_id before a strict provenance write, or explicitly accept NULL source foreign keys.")
    steps.append("Phase 2B should add an explicit write-db gate and keep dry-run as the default.")
    return steps


def _report_payload(result: dict[str, Any]) -> dict[str, Any]:
    plans = list(result.get("write_plans") or [])
    payload = dict(result)
    payload["write_plan_examples"] = [_short_plan(plan) for plan in plans[:5]]
    payload["sql_preview_examples"] = _sql_examples(plans)
    payload["next_steps"] = _next_steps(result)
    payload["database_written"] = False
    return payload


def _gate_next_steps(result: dict[str, Any]) -> list[str]:
    steps = [
        "Keep Phase 2B-0 in dry-run mode; do not execute the commented SQL preview.",
        "Future real writes must require an explicit --write-db flag, a transaction, rollback handling, and post-write verification.",
    ]
    if int(result.get("provenance_missing_count") or 0):
        steps.append("Backfill missing provenance or explicitly approve --allow-missing-provenance before any future write-db run.")
    if int(result.get("gate_blocked_count") or 0):
        steps.append("Resolve gate_blocking_errors before Phase 2B real-write preparation.")
    else:
        steps.append("All candidates passed the strict dry-run write gate; a future write phase still needs explicit operator approval.")
    return steps


def _gate_report_payload(result: dict[str, Any]) -> dict[str, Any]:
    plans = list(result.get("write_plans") or [])
    payload = dict(result)
    payload["write_plan_examples"] = [_short_plan(plan) for plan in plans[:5]]
    payload["sql_preview_examples"] = _sql_examples(plans)
    payload["next_steps"] = _gate_next_steps(result)
    payload["database_written"] = False
    return payload


def write_writer_dry_run_json(result: dict[str, Any], path: str | Path = DEFAULT_WRITER_REPORT_JSON) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_report_payload(result), ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return output


def write_writer_gate_dry_run_json(result: dict[str, Any], path: str | Path = DEFAULT_WRITER_GATE_REPORT_JSON) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_gate_report_payload(result), ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return output


def write_writer_dry_run_markdown(result: dict[str, Any], path: str | Path = DEFAULT_WRITER_REPORT_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _report_payload(result)
    plans = list(result.get("write_plans") or [])

    lines = [
        "# Knowledge Unit Writer Dry-run Report",
        "",
        "## Summary",
        "",
        f"- total_candidates: {payload.get('total_candidates', 0)}",
        f"- total_input_records: {payload.get('total_input_records', payload.get('total_candidates', 0))}",
        f"- non_accepted_skipped_count: {payload.get('non_accepted_skipped_count', 0)}",
        f"- write_ready_count: {payload.get('write_ready_count', 0)}",
        f"- blocked_count: {payload.get('blocked_count', 0)}",
        f"- counts_by_unit_type: {json.dumps(payload.get('counts_by_unit_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- target_table_counts: {json.dumps(payload.get('target_table_counts') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- duplicate_dedup_key_count: {payload.get('duplicate_dedup_key_count', 0)}",
        f"- blocking_errors_by_type: {json.dumps(payload.get('blocking_errors_by_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- warnings_by_type: {json.dumps(payload.get('warnings_by_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- extension_table_supported: {str(bool(payload.get('extension_table_supported'))).lower()}",
        f"- extension_table_preview_only: {str(bool(payload.get('extension_table_preview_only'))).lower()}",
        f"- can_enter_phase2b: {str(bool(payload.get('can_enter_phase2b'))).lower()}",
        "- database_written: false",
        "",
        "## Mapping Strategy",
        "",
        f"- dedup_strategy: {payload.get('dedup_strategy')}",
        f"- unit_type_target_strategy: {json.dumps(payload.get('unit_type_target_strategy') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- extension_table_strategy: {json.dumps(payload.get('extension_table_strategy') or {}, ensure_ascii=False, sort_keys=True)}",
        "- Phase 2A validates knowledge_units main-table mapping plus extension-table preview only.",
        "",
        "## Write Plan Examples",
        "",
    ]

    examples = payload.get("write_plan_examples") or []
    if examples:
        for item in examples:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## SQL Preview Examples", ""])
    sql_examples = payload.get("sql_preview_examples") or []
    if sql_examples:
        for sql in sql_examples:
            lines.extend(["```sql", sql, "```", ""])
    else:
        lines.append("- none")

    blocked = [plan for plan in plans if plan.get("blocking_errors")]
    lines.extend(["", "## Blocking Errors", ""])
    if blocked:
        for plan in blocked[:20]:
            lines.append(f"- {plan.get('candidate_id')}: {json.dumps(plan.get('blocking_errors') or [], ensure_ascii=False, sort_keys=True)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Warnings", ""])
    warning_items = []
    for plan in plans:
        for warning in plan.get("warnings") or []:
            warning_items.append(f"{plan.get('candidate_id')}: {json.dumps(warning, ensure_ascii=False, sort_keys=True)}")
            if len(warning_items) >= 30:
                break
        if len(warning_items) >= 30:
            break
    if warning_items:
        lines.extend(f"- {item}" for item in warning_items)
    else:
        lines.append("- none")

    lines.extend(["", "## Next Steps", ""])
    lines.extend(f"- {step}" for step in payload.get("next_steps") or [])
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- No INSERT, UPDATE, DELETE, schema migration, OCR, index rebuild, retrieval_service change, model call, or external API call was performed.",
        ]
    )

    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_writer_gate_dry_run_markdown(result: dict[str, Any], path: str | Path = DEFAULT_WRITER_GATE_REPORT_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _gate_report_payload(result)
    plans = list(result.get("write_plans") or [])

    lines = [
        "# Knowledge Unit Writer Gate Dry-run Report",
        "",
        "## Summary",
        "",
        f"- total_candidates: {payload.get('total_candidates', 0)}",
        f"- total_input_records: {payload.get('total_input_records', payload.get('total_candidates', 0))}",
        f"- non_accepted_skipped_count: {payload.get('non_accepted_skipped_count', 0)}",
        f"- write_ready_count: {payload.get('write_ready_count', 0)}",
        f"- gate_ready_count: {payload.get('gate_ready_count', 0)}",
        f"- gate_blocked_count: {payload.get('gate_blocked_count', 0)}",
        f"- provenance_ready_count: {payload.get('provenance_ready_count', 0)}",
        f"- provenance_partial_count: {payload.get('provenance_partial_count', 0)}",
        f"- provenance_missing_count: {payload.get('provenance_missing_count', 0)}",
        f"- counts_by_unit_type: {json.dumps(payload.get('counts_by_unit_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- target_table_counts: {json.dumps(payload.get('target_table_counts') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- duplicate_dedup_key_count: {payload.get('duplicate_dedup_key_count', 0)}",
        f"- blocking_errors_by_type: {json.dumps(payload.get('blocking_errors_by_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- warnings_by_type: {json.dumps(payload.get('warnings_by_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- provenance_warnings_by_type: {json.dumps(payload.get('provenance_warnings_by_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- allow_missing_provenance_default: {str(bool(payload.get('allow_missing_provenance_default'))).lower()}",
        f"- allow_missing_provenance: {str(bool(payload.get('allow_missing_provenance'))).lower()}",
        f"- write_db_required: {str(bool(payload.get('write_db_required'))).lower()}",
        f"- can_enter_phase2b_write: {str(bool(payload.get('can_enter_phase2b_write'))).lower()}",
        "- database_written: false",
        "",
        "## Gate Strategy",
        "",
        f"- transaction_strategy: {json.dumps(payload.get('transaction_strategy') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- rollback_strategy: {json.dumps(payload.get('rollback_strategy') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- post_write_verification_strategy: {json.dumps(payload.get('post_write_verification_strategy') or {}, ensure_ascii=False, sort_keys=True)}",
        "- No write operation is allowed without a future explicit --write-db flag.",
        "",
        "## Write Plan Examples",
        "",
    ]

    examples = payload.get("write_plan_examples") or []
    if examples:
        for item in examples:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    blocked = [plan for plan in plans if plan.get("gate_blocking_errors")]
    lines.extend(["", "## Gate Blocking Errors", ""])
    if blocked:
        for plan in blocked[:20]:
            lines.append(f"- {plan.get('candidate_id')}: {json.dumps(plan.get('gate_blocking_errors') or [], ensure_ascii=False, sort_keys=True)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Gate Warnings", ""])
    warning_items = []
    for plan in plans:
        for warning in plan.get("gate_warnings") or []:
            warning_items.append(f"{plan.get('candidate_id')}: {json.dumps(warning, ensure_ascii=False, sort_keys=True)}")
            if len(warning_items) >= 30:
                break
        if len(warning_items) >= 30:
            break
    if warning_items:
        lines.extend(f"- {item}" for item in warning_items)
    else:
        lines.append("- none")

    lines.extend(["", "## SQL Preview Examples", ""])
    sql_examples = payload.get("sql_preview_examples") or []
    if sql_examples:
        for sql in sql_examples:
            lines.extend(["```sql", sql, "```", ""])
    else:
        lines.append("- none")

    lines.extend(["", "## Next Steps", ""])
    lines.extend(f"- {step}" for step in payload.get("next_steps") or [])
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- No INSERT, UPDATE, DELETE, schema migration, OCR, index rebuild, retrieval_service change, model call, or external API call was performed.",
        ]
    )

    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def _comment_sql_block(sql: str) -> str:
    lines = str(sql or "").splitlines()
    return "\n".join(f"-- {line}" if line.strip() else "--" for line in lines)


def write_writer_sql_preview(result: dict[str, Any], path: str | Path = DEFAULT_WRITER_SQL_PREVIEW) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- Knowledge Unit Writer SQL Preview",
        "-- Phase 2A dry-run only. Every SQL line below is commented out intentionally.",
        "-- database_written=false",
        "",
    ]
    for idx, plan in enumerate(result.get("write_plans") or [], start=1):
        lines.extend(
            [
                f"-- ===== plan {idx}: {plan.get('candidate_id')} {plan.get('unit_type')} {plan.get('canonical_name')} =====",
                f"-- can_write={str(bool(plan.get('can_write'))).lower()} target_table={plan.get('target_table')} extension_table={plan.get('extension_table')}",
                f"-- blocking_errors={json.dumps(plan.get('blocking_errors') or [], ensure_ascii=False, sort_keys=True)}",
                f"-- warnings={json.dumps(plan.get('warnings') or [], ensure_ascii=False, sort_keys=True)}",
                "",
            ]
        )
        for sql in plan.get("sql_preview") or []:
            lines.append(_comment_sql_block(sql))
            lines.append("")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_writer_gate_sql_preview(result: dict[str, Any], path: str | Path = DEFAULT_WRITER_GATE_SQL_PREVIEW) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- Knowledge Unit Writer Gate SQL Preview",
        "-- Phase 2B-0 dry-run only. Every SQL line below is commented out intentionally.",
        "-- database_written=false",
        "-- write_db_required=true",
        f"-- allow_missing_provenance={str(bool(result.get('allow_missing_provenance'))).lower()}",
        "",
    ]
    for idx, plan in enumerate(result.get("write_plans") or [], start=1):
        gate = plan.get("write_gate") or {}
        lines.extend(
            [
                f"-- ===== gate plan {idx}: {plan.get('candidate_id')} {plan.get('unit_type')} {plan.get('canonical_name')} =====",
                f"-- map_can_write={str(bool(plan.get('can_write'))).lower()} gate_can_write={str(bool(plan.get('gate_can_write'))).lower()} target_table={plan.get('target_table')} extension_table={plan.get('extension_table')}",
                f"-- provenance_status={plan.get('provenance_status')} method={plan.get('provenance_backfill_method')}",
                f"-- gate_blocking_errors={json.dumps(gate.get('blocking_errors') or [], ensure_ascii=False, sort_keys=True)}",
                f"-- gate_warnings={json.dumps(gate.get('warnings') or [], ensure_ascii=False, sort_keys=True)}",
                "",
            ]
        )
        for sql in plan.get("sql_preview") or []:
            lines.append(_comment_sql_block(sql))
            lines.append("")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_writer_dry_run_outputs(
    result: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_WRITER_REPORT_MD,
    report_json: str | Path = DEFAULT_WRITER_REPORT_JSON,
    sql_preview: str | Path = DEFAULT_WRITER_SQL_PREVIEW,
) -> dict[str, str]:
    json_path = write_writer_dry_run_json(result, report_json)
    md_path = write_writer_dry_run_markdown(result, report_md)
    sql_path = write_writer_sql_preview(result, sql_preview)
    return {
        "report_md": str(md_path),
        "report_json": str(json_path),
        "sql_preview": str(sql_path),
    }


def write_writer_gate_dry_run_outputs(
    result: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_WRITER_GATE_REPORT_MD,
    report_json: str | Path = DEFAULT_WRITER_GATE_REPORT_JSON,
    sql_preview: str | Path = DEFAULT_WRITER_GATE_SQL_PREVIEW,
) -> dict[str, str]:
    json_path = write_writer_gate_dry_run_json(result, report_json)
    md_path = write_writer_gate_dry_run_markdown(result, report_md)
    sql_path = write_writer_gate_sql_preview(result, sql_preview)
    return {
        "report_md": str(md_path),
        "report_json": str(json_path),
        "sql_preview": str(sql_path),
    }
