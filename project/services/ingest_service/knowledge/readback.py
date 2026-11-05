from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from services.retrieval_service.config import load_config

from .provenance_backfill import DEFAULT_RUNS_DIR
from .writer import build_writer_gate_dry_run_from_path


TARGET_TABLE = "knowledge_units"

FIELD_CHECKS = (
    "candidate_id",
    "unit_type",
    "canonical_name",
    "content",
    "document_id",
    "source_chunk_id",
)

CORE_COLUMN_ALIASES = {
    "candidate_id": ("candidate_id",),
    "dedup_key": ("dedup_key",),
    "unit_type": ("unit_type",),
    "canonical_name": ("canonical_name", "title"),
    "content": ("content",),
    "document_id": ("document_id", "source_doc_id"),
    "source_chunk_id": ("source_chunk_id",),
}

SELECT_BASE_COLUMNS = (
    "id",
    "candidate_id",
    "dedup_key",
    "unit_code",
    "unit_type",
    "canonical_name",
    "title",
    "content",
    "document_id",
    "source_doc_id",
    "source_chunk_id",
    "meta_json",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_default(value: Any) -> str:
    return str(value)


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in counter.items()))


def _safe_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL identifier: {identifier}")
    return f"`{identifier}`"


def _sanitize_error(message: Any) -> str:
    text = str(message or "").strip()
    replacements = [
        (r"(?i)(password\s*=\s*)[^,\s;]+", r"\1<redacted>"),
        (r"(?i)(MYSQL_PASSWORD\s*=\s*)[^,\s;]+", r"\1<redacted>"),
        (r"(?i)(passwd\s*=\s*)[^,\s;]+", r"\1<redacted>"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    return text[:500]


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


def _cursor(connection: Any):
    return connection.cursor()


def _execute_select(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> None:
    normalized = " ".join(str(sql or "").split()).lower()
    if not normalized.startswith("select"):
        raise RuntimeError("readback_select_only_violation")
    cursor.execute(sql, params)


def _fetchone(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    _execute_select(cursor, sql, params)
    return cursor.fetchone()


def _fetchall_dict(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    _execute_select(cursor, sql, params)
    rows = list(cursor.fetchall() or [])
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(row) for row in rows if isinstance(row, dict)]

    description = getattr(cursor, "description", None) or []
    names = [str(item[0]) for item in description if item]
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
            continue
        out.append({name: row[index] if index < len(row) else None for index, name in enumerate(names)})
    return out


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


def _schema_columns(cursor: Any, table_name: str = TARGET_TABLE) -> list[str]:
    rows = _fetchall_dict(
        cursor,
        """
        SELECT COLUMN_NAME
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    columns: list[str] = []
    for row in rows:
        name = _text(row.get("COLUMN_NAME") or row.get("column_name") or row.get("COLUMN_NAME".lower()))
        if name:
            columns.append(name)
    return columns


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


def _candidate_dedup_key(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata_preview")
    if not isinstance(metadata, dict):
        metadata = {}
    return _text(candidate.get("dedup_key") or metadata.get("dedup_key"))


def _candidate_value(candidate: dict[str, Any], field: str) -> Any:
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    metadata = candidate.get("metadata_preview") if isinstance(candidate.get("metadata_preview"), dict) else {}
    if field == "candidate_id":
        return candidate.get("candidate_id") or metadata.get("candidate_id") or candidate.get("id")
    if field == "canonical_name":
        return candidate.get("canonical_name") or metadata.get("canonical_name") or candidate.get("title")
    if field == "document_id":
        return (
            candidate.get("document_id")
            or candidate.get("source_doc_id")
            or candidate.get("source_document_id")
            or source.get("document_id")
            or source.get("doc_id")
            or source.get("source_doc_id")
        )
    if field == "source_chunk_id":
        return candidate.get("source_chunk_id") or source.get("source_chunk_id") or source.get("chunk_id")
    return candidate.get(field) or metadata.get(field)


def _row_meta(row: dict[str, Any]) -> dict[str, Any]:
    return _json_loads_maybe(row.get("meta_json"))


def _row_logical_value(row: dict[str, Any], field: str) -> Any:
    meta = _row_meta(row)
    if field == "candidate_id":
        return row.get("candidate_id") or meta.get("candidate_id")
    if field == "dedup_key":
        return row.get("dedup_key") or meta.get("dedup_key")
    if field == "canonical_name":
        return row.get("canonical_name") or meta.get("canonical_name") or row.get("title")
    if field == "document_id":
        return row.get("document_id") if row.get("document_id") is not None else row.get("source_doc_id")
    if field == "source_chunk_id":
        return row.get("source_chunk_id")
    return row.get(field) if row.get(field) is not None else meta.get(field)


def _normalized_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _values_match(expected: Any, actual: Any) -> bool:
    return _normalized_scalar(expected) == _normalized_scalar(actual)


def _stable_unit_code_from_candidate(candidate: dict[str, Any]) -> str:
    value = _text(candidate.get("unit_code"))
    if value:
        return value
    raw = _candidate_dedup_key(candidate)
    base = re.sub(r"[^0-9A-Za-z_]+", "_", raw.lower()).strip("_")
    if not base:
        return ""
    if len(base) <= 128:
        return base
    import hashlib

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    keep = max(1, 128 - len(digest) - 1)
    return f"{base[:keep].rstrip('_')}_{digest}"


def _select_columns(schema_fields: set[str]) -> list[str]:
    return [column for column in SELECT_BASE_COLUMNS if column in schema_fields]


def _normalize_readback_row(row: dict[str, Any], *, query_mode: str) -> dict[str, Any]:
    normalized = dict(row)
    meta = _row_meta(row)
    normalized["_query_mode"] = query_mode
    normalized["_meta_candidate_id"] = meta.get("candidate_id")
    normalized["_meta_dedup_key"] = meta.get("dedup_key")
    normalized["_logical_dedup_key"] = _row_logical_value(row, "dedup_key")
    normalized["_logical_candidate_id"] = _row_logical_value(row, "candidate_id")
    normalized["_logical_canonical_name"] = _row_logical_value(row, "canonical_name")
    normalized["_logical_document_id"] = _row_logical_value(row, "document_id")
    normalized["_logical_source_chunk_id"] = _row_logical_value(row, "source_chunk_id")
    return normalized


def load_written_candidates(input_path: str) -> list[dict]:
    """Load the Phase 2B accepted pack as provenance-enhanced write plans.

    This is intentionally a no-DB operation. It mirrors the Phase 2B writer's
    input preparation so readback compares rows against the values that were
    actually eligible for the controlled write, including provenance backfill.
    """

    result = build_writer_gate_dry_run_from_path(input_path, runs_dir=DEFAULT_RUNS_DIR)
    return [dict(plan) for plan in result.get("write_plans") or [] if isinstance(plan, dict)]


def readback_knowledge_units_by_dedup_key(candidates: list[dict]) -> dict:
    expected = [dict(item) for item in candidates or [] if isinstance(item, dict)]
    result: dict[str, Any] = {
        "status": "ok",
        "target_table": TARGET_TABLE,
        "expected_count": len(expected),
        "rows": [],
        "schema_fields": [],
        "query_mode": None,
        "readonly": True,
        "database_written": False,
        "db_connection_opened": False,
        "errors": [],
    }
    if not expected:
        return result

    connection = None
    try:
        connection = _connect_mysql()
        result["db_connection_opened"] = True
        cursor = _cursor(connection)

        if not _table_exists(cursor):
            result.update(
                {
                    "status": "error",
                    "error_type": "target_table_missing",
                    "errors": [{"type": "target_table_missing", "message": "knowledge_units table does not exist."}],
                }
            )
            return result

        schema_fields = set(_schema_columns(cursor))
        result["schema_fields"] = sorted(schema_fields)
        select_columns = _select_columns(schema_fields)
        if not select_columns:
            result.update(
                {
                    "status": "error",
                    "error_type": "missing_selectable_columns",
                    "errors": [{"type": "missing_selectable_columns", "message": "knowledge_units has no selectable core columns."}],
                }
            )
            return result

        select_sql = ", ".join(_safe_identifier(column) for column in select_columns)
        if "dedup_key" in schema_fields:
            query_mode = "dedup_key"
            values = sorted({_candidate_dedup_key(candidate) for candidate in expected if _candidate_dedup_key(candidate)})
            where_sql = f"{_safe_identifier('dedup_key')} IN ({{placeholders}})"
        elif "unit_code" in schema_fields:
            query_mode = "unit_code_from_dedup_key"
            values = sorted({_stable_unit_code_from_candidate(candidate) for candidate in expected if _stable_unit_code_from_candidate(candidate)})
            where_sql = f"{_safe_identifier('unit_code')} IN ({{placeholders}})"
        elif "meta_json" in schema_fields:
            query_mode = "meta_json_dedup_key"
            values = sorted({_candidate_dedup_key(candidate) for candidate in expected if _candidate_dedup_key(candidate)})
            where_sql = "JSON_UNQUOTE(JSON_EXTRACT(`meta_json`, '$.dedup_key')) IN ({placeholders})"
        else:
            result.update(
                {
                    "status": "error",
                    "error_type": "missing_identity_column",
                    "errors": [{"type": "missing_identity_column", "message": "schema has no dedup_key, unit_code, or meta_json identity."}],
                }
            )
            return result

        result["query_mode"] = query_mode
        if not values:
            return result

        rows: list[dict[str, Any]] = []
        chunk_size = 200
        for start in range(0, len(values), chunk_size):
            chunk = values[start : start + chunk_size]
            placeholders = ", ".join(["%s"] * len(chunk))
            sql = f"SELECT {select_sql} FROM {_safe_identifier(TARGET_TABLE)} WHERE {where_sql.format(placeholders=placeholders)}"
            rows.extend(_fetchall_dict(cursor, sql, tuple(chunk)))
        result["rows"] = [_normalize_readback_row(row, query_mode=query_mode) for row in rows]
        return result
    except Exception as exc:
        result.update(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": _sanitize_error(exc),
                "errors": [{"type": type(exc).__name__, "message": _sanitize_error(exc)}],
                "rows": [],
            }
        )
        return result
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def compare_readback_with_candidates(candidates: list[dict], rows: list[dict]) -> dict:
    expected = [dict(item) for item in candidates or [] if isinstance(item, dict)]
    read_rows = [dict(row) for row in rows or [] if isinstance(row, dict)]
    expected_by_key = {_candidate_dedup_key(candidate): candidate for candidate in expected if _candidate_dedup_key(candidate)}

    rows_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_rows:
        key = _text(row.get("_logical_dedup_key") or _row_logical_value(row, "dedup_key"))
        if key:
            rows_by_key[key].append(row)

    missing_dedup_keys: list[str] = []
    mismatched_examples: list[dict[str, Any]] = []
    readback_examples: list[dict[str, Any]] = []
    field_match_count = 0
    field_mismatch_count = 0

    for dedup_key, candidate in expected_by_key.items():
        matched_rows = rows_by_key.get(dedup_key) or []
        if not matched_rows:
            missing_dedup_keys.append(dedup_key)
            continue
        row = matched_rows[0]
        checks: dict[str, bool] = {}
        expected_values: dict[str, Any] = {}
        actual_values: dict[str, Any] = {}
        for field in FIELD_CHECKS:
            expected_value = _candidate_value(candidate, field)
            actual_value = _row_logical_value(row, field)
            checks[field] = _values_match(expected_value, actual_value)
            expected_values[field] = expected_value
            actual_values[field] = actual_value

        if all(checks.values()):
            field_match_count += 1
        else:
            field_mismatch_count += 1
            if len(mismatched_examples) < 10:
                mismatched_examples.append(
                    {
                        "dedup_key": dedup_key,
                        "candidate_id": _candidate_value(candidate, "candidate_id"),
                        "field_matches": checks,
                        "expected": expected_values,
                        "actual": actual_values,
                    }
                )

        if len(readback_examples) < 10:
            readback_examples.append(
                {
                    "dedup_key": dedup_key,
                    "candidate_id": _row_logical_value(row, "candidate_id"),
                    "unit_type": _row_logical_value(row, "unit_type"),
                    "canonical_name": _row_logical_value(row, "canonical_name"),
                    "document_id": _row_logical_value(row, "document_id"),
                    "source_chunk_id": _row_logical_value(row, "source_chunk_id"),
                }
            )

    duplicate_count = sum(max(0, len(items) - 1) for items in rows_by_key.values())
    duplicate_dedup_keys = sorted(key for key, items in rows_by_key.items() if len(items) > 1)
    counts_by_unit_type = Counter(_text(_candidate_value(candidate, "unit_type")) or "unknown" for candidate in expected)
    found_counts_by_unit_type = Counter(
        _text(_row_logical_value(rows_by_key[key][0], "unit_type")) or "unknown"
        for key in expected_by_key
        if rows_by_key.get(key)
    )
    missing_count = len(missing_dedup_keys)
    found_count = len([key for key in expected_by_key if rows_by_key.get(key)])
    ok = missing_count == 0 and duplicate_count == 0 and field_mismatch_count == 0

    return {
        "status": "ok" if ok else "mismatch",
        "expected_count": len(expected),
        "expected_unique_dedup_key_count": len(expected_by_key),
        "found_count": found_count,
        "readback_row_count": len(read_rows),
        "missing_count": missing_count,
        "duplicate_count": duplicate_count,
        "field_match_count": field_match_count,
        "field_mismatch_count": field_mismatch_count,
        "counts_by_unit_type": _counter_dict(counts_by_unit_type),
        "found_counts_by_unit_type": _counter_dict(found_counts_by_unit_type),
        "missing_dedup_keys": missing_dedup_keys,
        "duplicate_dedup_keys": duplicate_dedup_keys,
        "mismatched_examples": mismatched_examples,
        "readback_examples": readback_examples,
        "field_checks": list(FIELD_CHECKS),
        "database_written": False,
        "readonly": True,
        "can_enter_phase2d": ok,
        "next_steps": (
            ["Proceed to Phase 2D planning after reviewing the readback report."]
            if ok
            else ["Resolve missing, duplicate, or mismatched knowledge_units rows before Phase 2D."]
        ),
    }


def to_jsonable(data: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(data, ensure_ascii=False, default=_json_default))
