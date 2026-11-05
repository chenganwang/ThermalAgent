from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_DB_WRITE_REPORT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_db_write_report.md"
DEFAULT_DB_WRITE_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_db_write_report.json"
DEFAULT_DB_WRITE_SQL_PREVIEW = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_db_write_sql_executed_preview.sql"
DEFAULT_DB_PREWRITE_SNAPSHOT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_db_prewrite_snapshot.json"
DEFAULT_DB_PREWRITE_SNAPSHOT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_db_prewrite_snapshot.md"


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(data: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    return output


def _snapshot(result: dict[str, Any]) -> dict[str, Any]:
    return dict(result.get("prewrite_snapshot") or {})


def write_prewrite_snapshot_json(result: dict[str, Any], path: str | Path = DEFAULT_DB_PREWRITE_SNAPSHOT_JSON) -> Path:
    snapshot = _snapshot(result)
    snapshot.setdefault("database_written", bool(result.get("database_written")))
    snapshot.setdefault("db_connection_opened", bool(result.get("db_connection_opened")))
    return _write_json(snapshot, path)


def write_db_write_report_json(result: dict[str, Any], path: str | Path = DEFAULT_DB_WRITE_REPORT_JSON) -> Path:
    payload = dict(result)
    payload["database_written"] = bool(result.get("database_written"))
    return _write_json(payload, path)


def write_prewrite_snapshot_markdown(result: dict[str, Any], path: str | Path = DEFAULT_DB_PREWRITE_SNAPSHOT_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = _snapshot(result)
    lines = [
        "# Knowledge Unit DB Prewrite Snapshot",
        "",
        f"- target_table: {snapshot.get('target_table', 'knowledge_units')}",
        f"- target_table_exists: {snapshot.get('target_table_exists')}",
        f"- schema_fields: {json.dumps(snapshot.get('schema_fields') or [], ensure_ascii=False)}",
        f"- prewrite_knowledge_units_count: {snapshot.get('prewrite_knowledge_units_count')}",
        f"- accepted_pack_count: {snapshot.get('accepted_pack_count')}",
        f"- identity_column: {snapshot.get('identity_column')}",
        f"- identity_unique: {snapshot.get('identity_unique')}",
        f"- existing_count: {snapshot.get('existing_count')}",
        f"- insert_planned_count: {snapshot.get('insert_planned_count')}",
        f"- update_planned_count: {snapshot.get('update_planned_count')}",
        f"- blocking_errors: {json.dumps(snapshot.get('blocking_errors') or [], ensure_ascii=False, sort_keys=True)}",
        "",
        "## Accepted Pack Existing",
        "",
    ]
    existing = snapshot.get("accepted_pack_existing") or {}
    if existing:
        for key, row_id in existing.items():
            lines.append(f"- {key}: id={row_id}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Snapshot is read-only and does not dump table contents or database credentials.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_db_write_report_markdown(result: dict[str, Any], path: str | Path = DEFAULT_DB_WRITE_REPORT_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    verification = result.get("post_write_verification") or {}
    lines = [
        "# Knowledge Unit DB Write Report",
        "",
        "## Summary",
        "",
        f"- status: {result.get('status')}",
        f"- write_db: {str(bool(result.get('write_db'))).lower()}",
        f"- total_candidates: {result.get('total_candidates', 0)}",
        f"- write_ready_count: {result.get('write_ready_count', 0)}",
        f"- gate_ready_count: {result.get('gate_ready_count', 0)}",
        f"- gate_blocked_count: {result.get('gate_blocked_count', 0)}",
        f"- database_written: {str(bool(result.get('database_written'))).lower()}",
        f"- db_connection_opened: {str(bool(result.get('db_connection_opened'))).lower()}",
        f"- committed: {str(bool(result.get('committed'))).lower()}",
        f"- rolled_back: {str(bool(result.get('rolled_back'))).lower()}",
        f"- inserted_count: {result.get('inserted_count', 0)}",
        f"- updated_count: {result.get('updated_count', 0)}",
        f"- unchanged_count: {result.get('unchanged_count', 0)}",
        f"- skipped_count: {result.get('skipped_count', 0)}",
        f"- failed_count: {result.get('failed_count', 0)}",
        f"- blocking_errors_by_type: {json.dumps(result.get('blocking_errors_by_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- warnings_by_type: {json.dumps(result.get('warnings_by_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- needs_manual_inspection: {str(bool(result.get('needs_manual_inspection'))).lower()}",
        "",
        "## Prewrite Snapshot",
        "",
        f"- target_table_exists: {_snapshot(result).get('target_table_exists')}",
        f"- prewrite_knowledge_units_count: {_snapshot(result).get('prewrite_knowledge_units_count')}",
        f"- existing_count: {_snapshot(result).get('existing_count')}",
        f"- insert_planned_count: {_snapshot(result).get('insert_planned_count')}",
        f"- update_planned_count: {_snapshot(result).get('update_planned_count')}",
        "",
        "## Post-write Verification",
        "",
        f"- postwrite_knowledge_units_count: {result.get('postwrite_knowledge_units_count')}",
        f"- verified_count: {verification.get('verified_count', 0)}",
        f"- verified_dedup_keys: {json.dumps(verification.get('verified_dedup_keys') or [], ensure_ascii=False)}",
        f"- missing_after_write: {json.dumps(verification.get('missing_after_write') or [], ensure_ascii=False)}",
        f"- core_fields_match: {str(bool(verification.get('core_fields_match'))).lower()}",
        f"- content_hash_match: {str(bool(verification.get('content_hash_match'))).lower()}",
        f"- mismatches: {json.dumps(verification.get('mismatches') or [], ensure_ascii=False, sort_keys=True)}",
        "",
        "## SQL Preview",
        "",
        f"- executed_sql_preview_count: {len(result.get('executed_sql_preview') or [])}",
        "- SQL preview uses placeholders and parameter hashes only; it does not include database credentials.",
        "",
        "## Error",
        "",
        f"- {result.get('error') or 'none'}",
        "",
        "## Boundary",
        "",
        "- This phase only handles the accepted candidate pack supplied to the script.",
        "- No schema migration, PDF ingest, OCR, index rebuild, retrieval_service change, model call, or external API call is performed.",
    ]
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_sql_executed_preview(result: dict[str, Any], path: str | Path = DEFAULT_DB_WRITE_SQL_PREVIEW) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- Knowledge Unit DB Write SQL Executed Preview",
        "-- Audit preview only. Statements are commented out intentionally.",
        f"-- database_written={str(bool(result.get('database_written'))).lower()}",
        f"-- committed={str(bool(result.get('committed'))).lower()}",
        f"-- rolled_back={str(bool(result.get('rolled_back'))).lower()}",
        "-- No database credentials or connection strings are recorded.",
        "",
    ]
    for idx, item in enumerate(result.get("executed_sql_preview") or [], start=1):
        lines.extend(
            [
                f"-- ===== statement {idx}: {item.get('action')} {item.get('candidate_id')} =====",
                f"-- params_count={item.get('params_count')} params_sha1={item.get('params_sha1')}",
            ]
        )
        for sql_line in str(item.get("sql") or "").splitlines():
            lines.append(f"-- {sql_line}" if sql_line.strip() else "--")
        lines.append("")
    if not result.get("executed_sql_preview"):
        lines.append("-- none")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_db_write_outputs(
    result: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_DB_WRITE_REPORT_MD,
    report_json: str | Path = DEFAULT_DB_WRITE_REPORT_JSON,
    sql_preview: str | Path = DEFAULT_DB_WRITE_SQL_PREVIEW,
    snapshot_json: str | Path = DEFAULT_DB_PREWRITE_SNAPSHOT_JSON,
    snapshot_md: str | Path = DEFAULT_DB_PREWRITE_SNAPSHOT_MD,
) -> dict[str, str]:
    report_json_path = write_db_write_report_json(result, report_json)
    report_md_path = write_db_write_report_markdown(result, report_md)
    sql_preview_path = write_sql_executed_preview(result, sql_preview)
    snapshot_json_path = write_prewrite_snapshot_json(result, snapshot_json)
    snapshot_md_path = write_prewrite_snapshot_markdown(result, snapshot_md)
    return {
        "report_md": str(report_md_path),
        "report_json": str(report_json_path),
        "sql_preview": str(sql_preview_path),
        "snapshot_json": str(snapshot_json_path),
        "snapshot_md": str(snapshot_md_path),
    }
