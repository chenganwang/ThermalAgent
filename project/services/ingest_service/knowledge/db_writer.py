from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from services.retrieval_service.config import load_config

from .provenance_backfill import DEFAULT_RUNS_DIR
from .write_gate import evaluate_write_gate
from .writer import build_writer_gate_dry_run_from_path


TARGET_TABLE = "knowledge_units"
EXPECTED_PHASE2B_COUNT = 10

JSON_COLUMNS = {
    "keywords",
    "related_formula_ids",
    "related_component_ids",
    "related_path_ids",
    "related_fault_ids",
    "related_visual_template_ids",
    "meta_json",
}

PREFERRED_IDENTITY_COLUMNS = ("dedup_key", "unit_code")
CORE_COLUMN_ALIASES = {
    "unit_type": ("unit_type",),
    "canonical_name": ("canonical_name", "title"),
    "content": ("content",),
    "dedup_key": ("dedup_key", "unit_code"),
    "document_id": ("document_id", "source_doc_id"),
    "source_chunk_id": ("source_chunk_id",),
}


def _json_default(value: Any) -> str:
    return str(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _issue(candidate_id: str, issue_type: str, message: str) -> dict[str, str]:
    return {"candidate_id": candidate_id or "unknown_candidate", "type": issue_type, "message": message}


def _metadata(plan: dict[str, Any]) -> dict[str, Any]:
    value = plan.get("metadata_preview")
    return value if isinstance(value, dict) else {}


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in counter.items()))


def _issue_counts(plans: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for plan in plans:
        for item in plan.get(field) or []:
            if isinstance(item, dict):
                counter[_text(item.get("type")) or "unknown"] += 1
    return _counter_dict(counter)


def _safe_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL identifier: {identifier}")
    return f"`{identifier}`"


def _cursor(connection: Any):
    return connection.cursor()


def _execute(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> None:
    cursor.execute(sql, params)


def _fetchone(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    _execute(cursor, sql, params)
    return cursor.fetchone()


def _fetchall(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    _execute(cursor, sql, params)
    rows = cursor.fetchall()
    return list(rows or [])


def _row_value(row: Any, key: str | int = 0) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        if isinstance(key, str):
            return row.get(key)
        values = list(row.values())
        return values[key] if len(values) > key else None
    try:
        return row[key]  # type: ignore[index]
    except Exception:
        return None


def _connect_mysql():
    try:
        import mysql.connector  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised through caller error handling
        raise RuntimeError("mysql_connector_unavailable") from exc

    cfg = load_config()
    return mysql.connector.connect(
        host=cfg.mysql.host,
        port=cfg.mysql.port,
        user=cfg.mysql.user,
        password=cfg.mysql.password,
        database=cfg.mysql.database,
        autocommit=False,
        charset="utf8mb4",
        use_unicode=True,
    )


def load_accepted_write_plan(input_path: str) -> list[dict]:
    """Load accepted candidates and return provenance-enhanced gated write plans.

    This function does not open a database connection. It only reuses the
    Phase 2B-0 dry-run gate pipeline and returns plans that can later be
    checked by ``preflight_validate_write_plan``.
    """

    result = build_writer_gate_dry_run_from_path(input_path, runs_dir=DEFAULT_RUNS_DIR)
    return list(result.get("write_plans") or [])


def _plan_review_status(plan: dict[str, Any]) -> str:
    return _text(plan.get("review_status") or _metadata(plan).get("review_status"))


def _plan_blocking_errors(plan: dict[str, Any], allow_missing_provenance: bool) -> list[dict[str, str]]:
    candidate_id = _text(plan.get("candidate_id"))
    gate = evaluate_write_gate(plan, allow_missing_provenance=allow_missing_provenance)
    errors = list(plan.get("blocking_errors") or []) + list(gate.get("blocking_errors") or [])

    if not bool(plan.get("can_write")):
        errors.append(_issue(candidate_id, "mapping_can_write_false", "writer mapping marked this candidate as not write-ready."))
    if _plan_review_status(plan) != "accepted":
        errors.append(_issue(candidate_id, "review_status_not_accepted", "only accepted candidates can be written."))
    if _text(plan.get("provenance_status")) != "ready":
        errors.append(
            _issue(
                candidate_id,
                "provenance_not_ready",
                "Phase 2B controlled write requires provenance_status=ready for every accepted candidate.",
            )
        )
    if not _present(plan.get("document_id")):
        errors.append(_issue(candidate_id, "missing_document_id", "document_id/source_doc_id is required for Phase 2B write."))
    if not _present(plan.get("source_chunk_id")):
        errors.append(_issue(candidate_id, "missing_source_chunk_id", "source_chunk_id is required for Phase 2B write."))
    return _dedupe_issues(errors)


def _plan_warnings(plan: dict[str, Any], allow_missing_provenance: bool) -> list[dict[str, str]]:
    gate = evaluate_write_gate(plan, allow_missing_provenance=allow_missing_provenance)
    return _dedupe_issues(list(plan.get("warnings") or []) + list(gate.get("warnings") or []))


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        item = {
            "candidate_id": _text(issue.get("candidate_id")),
            "type": _text(issue.get("type")) or "unknown",
            "message": _text(issue.get("message")),
        }
        marker = (item["candidate_id"], item["type"], item["message"])
        if marker not in seen:
            seen.add(marker)
            deduped.append(item)
    return deduped


def preflight_validate_write_plan(write_plan: list[dict]) -> dict:
    plans = [dict(plan) for plan in write_plan or [] if isinstance(plan, dict)]
    blocking_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    valid_plans: list[dict[str, Any]] = []
    blocked_plans: list[dict[str, Any]] = []

    dedup_counter = Counter(_text(plan.get("dedup_key")) for plan in plans if _text(plan.get("dedup_key")))
    for plan in plans:
        candidate_id = _text(plan.get("candidate_id"))
        errors = _plan_blocking_errors(plan, allow_missing_provenance=False)
        warnings = _plan_warnings(plan, allow_missing_provenance=False)

        dedup_key = _text(plan.get("dedup_key"))
        if dedup_key and dedup_counter[dedup_key] > 1:
            errors.append(_issue(candidate_id, "duplicate_dedup_key_in_write_pack", "duplicate dedup_key in accepted write pack."))

        plan["db_writer_blocking_errors"] = _dedupe_issues(errors)
        plan["db_writer_warnings"] = _dedupe_issues(warnings)

        for issue in plan["db_writer_blocking_errors"]:
            blocking_counter[issue["type"]] += 1
        for issue in plan["db_writer_warnings"]:
            warning_counter[issue["type"]] += 1

        if plan["db_writer_blocking_errors"]:
            blocked_plans.append(plan)
        else:
            valid_plans.append(plan)

    return {
        "valid": not blocked_plans,
        "total_candidates": len(plans),
        "write_ready_count": len(valid_plans),
        "gate_ready_count": len(valid_plans),
        "gate_blocked_count": len(blocked_plans),
        "blocked_count": len(blocked_plans),
        "blocking_errors_by_type": _counter_dict(blocking_counter),
        "warnings_by_type": _counter_dict(warning_counter),
        "valid_candidate_ids": [_text(plan.get("candidate_id")) for plan in valid_plans],
        "blocked_candidate_ids": [_text(plan.get("candidate_id")) for plan in blocked_plans],
        "blocked_examples": [
            {
                "candidate_id": plan.get("candidate_id"),
                "dedup_key": plan.get("dedup_key"),
                "blocking_errors": plan.get("db_writer_blocking_errors") or [],
            }
            for plan in blocked_plans[:10]
        ],
    }


def _schema_columns(cursor: Any, table_name: str = TARGET_TABLE) -> dict[str, dict[str, Any]]:
    rows = _fetchall(
        cursor,
        """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    columns: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = _text(_row_value(row, "COLUMN_NAME") or _row_value(row, 0))
        if not name:
            continue
        columns[name] = {
            "data_type": _text(_row_value(row, "DATA_TYPE") or _row_value(row, 1)),
            "nullable": _text(_row_value(row, "IS_NULLABLE") or _row_value(row, 2)),
            "column_key": _text(_row_value(row, "COLUMN_KEY") or _row_value(row, 3)),
        }
    return columns


def _table_exists(cursor: Any, table_name: str = TARGET_TABLE) -> bool:
    row = _fetchone(
        cursor,
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = %s
        """,
        (table_name,),
    )
    return bool(int(_row_value(row, 0) or 0) > 0)


def _count_rows(cursor: Any, table_name: str = TARGET_TABLE) -> int:
    row = _fetchone(cursor, f"SELECT COUNT(*) FROM {_safe_identifier(table_name)}")
    return int(_row_value(row, 0) or 0)


def _unique_indexes(cursor: Any, table_name: str = TARGET_TABLE) -> dict[str, list[str]]:
    rows = _fetchall(
        cursor,
        """
        SELECT INDEX_NAME, COLUMN_NAME
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND NON_UNIQUE = 0
        ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """,
        (table_name,),
    )
    indexes: dict[str, list[str]] = {}
    for row in rows:
        index_name = _text(_row_value(row, "INDEX_NAME") or _row_value(row, 0))
        column_name = _text(_row_value(row, "COLUMN_NAME") or _row_value(row, 1))
        if index_name and column_name:
            indexes.setdefault(index_name, []).append(column_name)
    return indexes


def _identity_column(schema_fields: set[str]) -> str | None:
    for column in PREFERRED_IDENTITY_COLUMNS:
        if column in schema_fields:
            return column
    return None


def _identity_value(plan: dict[str, Any], identity_column: str | None) -> str:
    if identity_column == "dedup_key":
        return _text(plan.get("dedup_key"))
    if identity_column == "unit_code":
        return _text(plan.get("unit_code"))
    return ""


def _unique_identity_supported(unique_indexes: dict[str, list[str]], identity_column: str | None) -> bool:
    if not identity_column:
        return False
    return any(columns == [identity_column] for columns in unique_indexes.values())


def _existing_identity_map(cursor: Any, plans: list[dict[str, Any]], identity_column: str | None) -> dict[str, int]:
    if not identity_column:
        return {}
    existing: dict[str, int] = {}
    column = _safe_identifier(identity_column)
    for plan in plans:
        value = _identity_value(plan, identity_column)
        if not value:
            continue
        row = _fetchone(cursor, f"SELECT id FROM {TARGET_TABLE} WHERE {column} = %s LIMIT 1", (value,))
        row_id = _row_value(row, 0)
        if row_id is not None:
            existing[value] = int(row_id)
    return existing


def _json_text(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=_json_default)


def _json_loads_maybe(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metadata_for_write(plan: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(_metadata(plan))
    metadata.update(
        {
            "candidate_id": plan.get("candidate_id"),
            "dedup_key": plan.get("dedup_key"),
            "canonical_name": plan.get("canonical_name"),
            "source_run_name": plan.get("source_run_name"),
            "source_asset_id": plan.get("source_asset_id"),
            "provenance_status": plan.get("provenance_status"),
            "provenance_backfill_method": plan.get("provenance_backfill_method"),
            "writer_phase": "phase_2b_controlled_write",
            "writer_database_written": True,
        }
    )
    properties = plan.get("properties")
    if isinstance(properties, dict):
        metadata["properties"] = properties
    return {key: value for key, value in metadata.items() if value not in (None, "", [], {})}


def _row_data_for_plan(plan: dict[str, Any], schema_fields: set[str]) -> tuple[dict[str, Any], list[str]]:
    skipped: list[str] = []
    title = _text(plan.get("title") or plan.get("canonical_name")) or "untitled knowledge unit"
    summary = _text(plan.get("content"))[:512]
    metadata = _metadata_for_write(plan)
    desired: dict[str, Any] = {
        "unit_code": _text(plan.get("unit_code")),
        "dedup_key": _text(plan.get("dedup_key")),
        "unit_type": _text(plan.get("unit_type")),
        "canonical_name": _text(plan.get("canonical_name")),
        "title": title,
        "summary": summary,
        "content": _text(plan.get("content")),
        "domain": "chip_liquid_cooling",
        "source_doc_id": plan.get("document_id"),
        "document_id": plan.get("document_id"),
        "source_chunk_id": plan.get("source_chunk_id"),
        "source_asset_id": plan.get("source_asset_id"),
        "keywords": _json_text(plan.get("keywords") or []),
        "confidence_score": float(plan.get("confidence") or 0.0),
        "confidence": float(plan.get("confidence") or 0.0),
        "review_status": "reviewed",
        "meta_json": _json_text(metadata),
    }
    row = {column: value for column, value in desired.items() if column in schema_fields}
    for column in desired:
        if column not in schema_fields and column in {
            "dedup_key",
            "canonical_name",
            "document_id",
            "source_asset_id",
            "confidence",
        }:
            skipped.append(column)
    return row, skipped


def _missing_core_mappings(schema_fields: set[str]) -> list[str]:
    missing: list[str] = []
    for logical_name, aliases in CORE_COLUMN_ALIASES.items():
        if not any(alias in schema_fields for alias in aliases):
            missing.append(logical_name)
    return missing


def _insert_sql(row: dict[str, Any], *, unique_identity: bool, has_updated_at: bool) -> tuple[str, tuple[Any, ...]]:
    columns = list(row.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(_safe_identifier(column) for column in columns)
    update_columns = [column for column in columns if column not in {"id", "unit_code", "dedup_key"}]
    update_sql = ", ".join(f"{_safe_identifier(column)} = VALUES({_safe_identifier(column)})" for column in update_columns)
    if has_updated_at and "updated_at" not in columns:
        update_sql = (update_sql + ", " if update_sql else "") + "updated_at = CURRENT_TIMESTAMP"
    sql = f"INSERT INTO {TARGET_TABLE} ({column_sql}) VALUES ({placeholders})"
    if unique_identity:
        sql += f" ON DUPLICATE KEY UPDATE {update_sql}"
    return sql, tuple(row[column] for column in columns)


def _update_sql(row: dict[str, Any], row_id: int, *, has_updated_at: bool) -> tuple[str, tuple[Any, ...]]:
    update_columns = [column for column in row.keys() if column not in {"id", "unit_code", "dedup_key"}]
    assignments = ", ".join(f"{_safe_identifier(column)} = %s" for column in update_columns)
    if has_updated_at and "updated_at" not in row:
        assignments = (assignments + ", " if assignments else "") + "updated_at = CURRENT_TIMESTAMP"
    sql = f"UPDATE {TARGET_TABLE} SET {assignments} WHERE id = %s"
    return sql, tuple(row[column] for column in update_columns) + (int(row_id),)


def _redacted_sql_record(action: str, candidate_id: str, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "action": action,
        "candidate_id": candidate_id,
        "sql": sql,
        "params_count": len(params),
        "params_sha1": hashlib.sha1(repr(params).encode("utf-8")).hexdigest()[:16],
    }


def _build_prewrite_snapshot(cursor: Any, plans: list[dict[str, Any]]) -> dict[str, Any]:
    table_exists = _table_exists(cursor)
    if not table_exists:
        return {
            "target_table": TARGET_TABLE,
            "target_table_exists": False,
            "schema_fields": [],
            "schema_field_details": {},
            "prewrite_knowledge_units_count": None,
            "accepted_pack_count": len(plans),
            "identity_column": None,
            "identity_unique": False,
            "existing_count": 0,
            "insert_planned_count": 0,
            "update_planned_count": 0,
            "accepted_pack_existing": {},
            "blocking_errors": [{"type": "target_table_missing", "message": "knowledge_units table does not exist."}],
        }

    schema = _schema_columns(cursor)
    schema_fields = set(schema.keys())
    unique_indexes = _unique_indexes(cursor)
    identity = _identity_column(schema_fields)
    existing = _existing_identity_map(cursor, plans, identity)
    identity_unique = _unique_identity_supported(unique_indexes, identity)
    missing_core = _missing_core_mappings(schema_fields)
    blocking_errors: list[dict[str, str]] = []
    if not identity:
        blocking_errors.append({"type": "missing_identity_column", "message": "schema has neither dedup_key nor unit_code."})
    if missing_core:
        blocking_errors.append(
            {
                "type": "missing_core_schema_fields",
                "message": "schema cannot store core fields: " + ", ".join(missing_core),
            }
        )

    identity_values = [_identity_value(plan, identity) for plan in plans] if identity else []
    return {
        "target_table": TARGET_TABLE,
        "target_table_exists": True,
        "schema_fields": list(schema.keys()),
        "schema_field_details": schema,
        "unique_indexes": unique_indexes,
        "identity_column": identity,
        "identity_unique": identity_unique,
        "prewrite_knowledge_units_count": _count_rows(cursor),
        "accepted_pack_count": len(plans),
        "accepted_pack_identity_values": identity_values,
        "accepted_pack_existing": existing,
        "existing_count": len(existing),
        "insert_planned_count": len([value for value in identity_values if value and value not in existing]),
        "update_planned_count": len([value for value in identity_values if value and value in existing]),
        "blocking_errors": blocking_errors,
    }


def _dry_run_snapshot(plans: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "target_table": TARGET_TABLE,
        "target_table_exists": None,
        "schema_fields": [],
        "prewrite_knowledge_units_count": None,
        "accepted_pack_count": len(plans),
        "existing_count": None,
        "insert_planned_count": None,
        "update_planned_count": None,
        "snapshot_mode": "dry_run_no_db_connection",
        "database_written": False,
        "db_connection_opened": False,
    }


def _verify_rows(cursor: Any, plans: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    identity = snapshot.get("identity_column")
    schema_fields = set(snapshot.get("schema_fields") or [])
    verified: list[str] = []
    missing: list[str] = []
    mismatches: list[dict[str, Any]] = []
    rows_by_identity: dict[str, Any] = {}
    column = _safe_identifier(str(identity)) if identity else ""

    for plan in plans:
        value = _identity_value(plan, identity)
        if not value:
            missing.append(_text(plan.get("dedup_key") or plan.get("candidate_id")))
            continue
        expected = {
            "unit_type": _text(plan.get("unit_type")),
            "title": _text(plan.get("title") or plan.get("canonical_name")),
            "content": _text(plan.get("content")),
            "source_doc_id": str(plan.get("document_id")),
            "source_chunk_id": str(plan.get("source_chunk_id")),
            "meta_json": "",
        }
        fields_to_check = [field for field in expected if field in schema_fields]
        select_fields = ", ".join(_safe_identifier(field) for field in fields_to_check) or "id"
        row = _fetchone(cursor, f"SELECT {select_fields} FROM {TARGET_TABLE} WHERE {column} = %s LIMIT 1", (value,))
        if not row:
            missing.append(value)
            continue
        rows_by_identity[value] = row
        checked_fields: dict[str, bool] = {}
        actual_by_field: dict[str, Any] = {}
        for index, field in enumerate(fields_to_check):
            actual_by_field[field] = _row_value(row, field) if isinstance(row, dict) else _row_value(row, index)
        for field in fields_to_check:
            if field == "meta_json":
                continue
            expected_value = expected[field]
            actual = actual_by_field.get(field)
            checked_fields[field] = str(actual) == str(expected_value)
        if "meta_json" in actual_by_field:
            meta = _json_loads_maybe(actual_by_field.get("meta_json"))
            checked_fields["meta_json.candidate_id"] = _text(meta.get("candidate_id")) == _text(plan.get("candidate_id"))
            checked_fields["meta_json.dedup_key"] = _text(meta.get("dedup_key")) == _text(plan.get("dedup_key"))
            checked_fields["meta_json.canonical_name"] = _text(meta.get("canonical_name")) == _text(plan.get("canonical_name"))
        if checked_fields and not all(checked_fields.values()):
            mismatches.append(
                {
                    "identity": value,
                    "candidate_id": plan.get("candidate_id"),
                    "checked_fields": checked_fields,
                }
            )
        else:
            verified.append(value)

    return {
        "verified_dedup_keys": [str(plan.get("dedup_key")) for plan in plans if _identity_value(plan, identity) in verified],
        "verified_identity_values": verified,
        "missing_after_write": missing,
        "core_fields_match": not mismatches and not missing,
        "content_hash_match": not mismatches and not missing,
        "mismatches": mismatches,
        "verified_count": len(verified),
    }


def post_write_verify(write_result: dict) -> dict:
    return dict(write_result.get("post_write_verification") or {})


def write_knowledge_units_transactional(
    write_plan: list[dict],
    *,
    write_db: bool,
    allow_missing_provenance: bool = False,
) -> dict:
    plans = [dict(plan) for plan in write_plan or [] if isinstance(plan, dict)]
    preflight = preflight_validate_write_plan(plans)
    result: dict[str, Any] = {
        "status": "dry_run" if not write_db else "pending",
        "write_db": bool(write_db),
        "allow_missing_provenance": bool(allow_missing_provenance),
        "total_candidates": len(plans),
        "write_ready_count": preflight.get("write_ready_count", 0),
        "gate_ready_count": preflight.get("gate_ready_count", 0),
        "gate_blocked_count": preflight.get("gate_blocked_count", 0),
        "blocked_count": preflight.get("blocked_count", 0),
        "blocking_errors_by_type": dict(preflight.get("blocking_errors_by_type") or {}),
        "warnings_by_type": dict(preflight.get("warnings_by_type") or {}),
        "database_written": False,
        "db_connection_opened": False,
        "committed": False,
        "rolled_back": False,
        "inserted_count": 0,
        "updated_count": 0,
        "unchanged_count": 0,
        "skipped_count": len(plans) if not write_db else 0,
        "failed_count": 0,
        "executed_sql_preview": [],
        "preflight": preflight,
        "prewrite_snapshot": _dry_run_snapshot(plans),
        "post_write_verification": {
            "verified_dedup_keys": [],
            "missing_after_write": [],
            "core_fields_match": False,
            "content_hash_match": False,
            "verified_count": 0,
        },
        "needs_manual_inspection": False,
    }

    if not write_db:
        result["status"] = "dry_run"
        result["next_steps"] = ["Rerun with --write-db for the controlled 10-record transaction after reviewing this dry-run report."]
        return result

    if not preflight.get("valid"):
        result["status"] = "blocked"
        result["skipped_count"] = len(plans)
        result["next_steps"] = ["Resolve db_writer_blocking_errors before attempting --write-db again."]
        return result

    connection = None
    try:
        connection = _connect_mysql()
        result["db_connection_opened"] = True
        cursor = _cursor(connection)
        snapshot = _build_prewrite_snapshot(cursor, plans)
        result["prewrite_snapshot"] = snapshot

        for issue in snapshot.get("blocking_errors") or []:
            issue_type = _text(issue.get("type")) or "schema_blocking_error"
            result["blocking_errors_by_type"][issue_type] = int(result["blocking_errors_by_type"].get(issue_type, 0)) + 1
        if snapshot.get("blocking_errors"):
            result["status"] = "blocked"
            result["skipped_count"] = len(plans)
            return result

        schema_fields = set(snapshot.get("schema_fields") or [])
        identity = snapshot.get("identity_column")
        identity_unique = bool(snapshot.get("identity_unique"))
        has_updated_at = "updated_at" in schema_fields
        existing = dict(snapshot.get("accepted_pack_existing") or {})

        if hasattr(connection, "start_transaction"):
            try:
                connection.start_transaction()
            except Exception as exc:
                if "already in progress" not in str(exc).lower():
                    raise
                result["warnings_by_type"]["transaction_already_in_progress"] = int(
                    result["warnings_by_type"].get("transaction_already_in_progress", 0)
                ) + 1

        for plan in plans:
            candidate_id = _text(plan.get("candidate_id"))
            row, skipped_fields = _row_data_for_plan(plan, schema_fields)
            for field in skipped_fields:
                result["warnings_by_type"][f"skipped_field:{field}"] = int(result["warnings_by_type"].get(f"skipped_field:{field}", 0)) + 1
            identity_value = _identity_value(plan, identity)
            if not row or not identity_value:
                result["failed_count"] += 1
                raise RuntimeError(f"cannot build write row for candidate_id={candidate_id}")

            if identity_unique:
                sql, params = _insert_sql(row, unique_identity=True, has_updated_at=has_updated_at)
                _execute(cursor, sql, params)
                rowcount = int(getattr(cursor, "rowcount", 0) or 0)
                result["executed_sql_preview"].append(_redacted_sql_record("upsert", candidate_id, sql, params))
                if identity_value in existing:
                    if rowcount == 0:
                        result["unchanged_count"] += 1
                    else:
                        result["updated_count"] += 1
                else:
                    result["inserted_count"] += 1
            else:
                row_id = existing.get(identity_value)
                if row_id:
                    sql, params = _update_sql(row, int(row_id), has_updated_at=has_updated_at)
                    _execute(cursor, sql, params)
                    rowcount = int(getattr(cursor, "rowcount", 0) or 0)
                    result["executed_sql_preview"].append(_redacted_sql_record("update", candidate_id, sql, params))
                    if rowcount == 0:
                        result["unchanged_count"] += 1
                    else:
                        result["updated_count"] += 1
                else:
                    sql, params = _insert_sql(row, unique_identity=False, has_updated_at=has_updated_at)
                    _execute(cursor, sql, params)
                    result["executed_sql_preview"].append(_redacted_sql_record("insert", candidate_id, sql, params))
                    result["inserted_count"] += 1

        verification = _verify_rows(cursor, plans, snapshot)
        result["post_write_verification"] = verification
        if verification.get("missing_after_write") or not verification.get("core_fields_match"):
            raise RuntimeError("post_write_verification_failed")

        if hasattr(connection, "commit"):
            connection.commit()
        result["committed"] = True
        result["database_written"] = True
        result["status"] = "ok"
        result["skipped_count"] = 0

        try:
            cursor_after = _cursor(connection)
            result["postwrite_knowledge_units_count"] = _count_rows(cursor_after)
        except Exception as exc:
            result["needs_manual_inspection"] = True
            result["post_commit_warning"] = f"post_commit_count_failed:{type(exc).__name__}"
        return result
    except Exception as exc:
        result["status"] = "error"
        result["failed_count"] = max(1, int(result.get("failed_count") or 0))
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["database_written"] = False
        if connection is not None and not result.get("committed"):
            try:
                connection.rollback()
                result["rolled_back"] = True
            except Exception as rollback_exc:
                result["rollback_error"] = f"{type(rollback_exc).__name__}: {rollback_exc}"
        return result
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
