from __future__ import annotations

import re
from typing import Any, Callable

from services.retrieval_service.config import AppConfig, load_config

from .query_builder import (
    analyze_shadow_query,
    build_where_clause,
    normalize_unit_types,
    safe_identifier,
    score_row,
    selectable_columns,
)
from .schema import KnowledgeUnitSearchResult, hit_from_row


TARGET_TABLE = "knowledge_units"
ConnectorFactory = Callable[[], Any]


def _sanitize_error(message: Any) -> str:
    text = str(message or "").strip()
    replacements = [
        (r"(?i)(password\s*=\s*)[^,\s;]+", r"\1<redacted>"),
        (r"(?i)(MYSQL_PASSWORD\s*=\s*)[^,\s;]+", r"\1<redacted>"),
        (r"(?i)(passwd\s*=\s*)[^,\s;]+", r"\1<redacted>"),
        (r"(?i)(://[^:\s/]+:)[^@\s/]+(@)", r"\1<redacted>\2"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    return text[:500]


def _connect_mysql(cfg: AppConfig | None = None) -> Any:
    try:
        import mysql.connector  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised through caller error handling
        raise RuntimeError("mysql_connector_unavailable") from exc

    app_cfg = cfg or load_config()
    return mysql.connector.connect(
        host=app_cfg.mysql.host,
        port=app_cfg.mysql.port,
        user=app_cfg.mysql.user,
        password=app_cfg.mysql.password,
        database=app_cfg.mysql.database,
        autocommit=True,
        charset="utf8mb4",
        use_unicode=True,
    )


def _cursor(connection: Any) -> Any:
    try:
        return connection.cursor(dictionary=True)
    except TypeError:
        return connection.cursor()


def _execute_select(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> None:
    normalized = " ".join(str(sql or "").split()).lower()
    if not normalized.startswith("select"):
        raise RuntimeError("knowledge_units_adapter_select_only_violation")
    forbidden = (" insert ", " update ", " delete ", " alter ", " drop ", " truncate ", " create ", " replace ")
    wrapped = f" {normalized} "
    if any(token in wrapped for token in forbidden):
        raise RuntimeError("knowledge_units_adapter_select_only_violation")
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
        name = str(row.get("COLUMN_NAME") or row.get("column_name") or "").strip()
        if name:
            columns.append(name)
    return columns


def _closed(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        pass


def _stable_row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("unit_type") or ""),
        str(row.get("unit_code") or row.get("dedup_key") or row.get("title") or ""),
        str(row.get("id") or ""),
    )


class KnowledgeUnitsRetrievalAdapter:
    """SELECT-only adapter for Phase 2D shadow/evaluation retrieval.

    The adapter is disabled by default and is not imported by the main agent
    path. It returns graceful result dictionaries instead of raising database
    errors into callers.
    """

    def __init__(
        self,
        *,
        cfg: AppConfig | None = None,
        enabled: bool = False,
        table_name: str = TARGET_TABLE,
        connector: ConnectorFactory | None = None,
    ) -> None:
        self.cfg = cfg
        self.enabled = bool(enabled)
        self.table_name = table_name
        self.connector = connector

    def _connect(self) -> Any:
        if self.connector is not None:
            return self.connector()
        return _connect_mysql(self.cfg)

    def search(
        self,
        query: str,
        *,
        unit_types: list[str] | tuple[str, ...] | set[str] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        filters = normalize_unit_types(unit_types)
        query_analysis = analyze_shadow_query(query)
        terms = list(query_analysis.get("match_terms") or [])
        unit_type_hints = list(query_analysis.get("unit_type_hints") or [])
        query_debug_info = dict(query_analysis.get("query_debug_info") or {})
        if not self.enabled:
            return KnowledgeUnitSearchResult(
                query=query,
                unit_type_filter=filters,
                status="disabled",
                enabled=False,
                query_terms=terms,
                query_debug_info=query_debug_info,
            ).to_dict()

        connection = None
        db_connection_opened = False
        try:
            table_name = self.table_name
            safe_table = safe_identifier(table_name)
            connection = self._connect()
            db_connection_opened = True
            cursor = _cursor(connection)

            if not _table_exists(cursor, table_name):
                return KnowledgeUnitSearchResult(
                    query=query,
                    unit_type_filter=filters,
                    status="error",
                    enabled=True,
                    error_type="target_table_missing",
                    error="knowledge_units table does not exist.",
                    query_terms=terms,
                    query_debug_info=query_debug_info,
                    db_connection_opened=db_connection_opened,
                ).to_dict()

            schema_fields = set(_schema_columns(cursor, table_name))
            select_columns = selectable_columns(schema_fields)
            if not select_columns:
                return KnowledgeUnitSearchResult(
                    query=query,
                    unit_type_filter=filters,
                    status="error",
                    enabled=True,
                    error_type="missing_selectable_columns",
                    error="knowledge_units has no selectable core columns.",
                    schema_fields=sorted(schema_fields),
                    query_terms=terms,
                    query_debug_info=query_debug_info,
                    db_connection_opened=db_connection_opened,
                ).to_dict()

            where_sql, params = build_where_clause(schema_fields=schema_fields, query_terms=terms, unit_types=filters)
            select_sql = ", ".join(safe_identifier(column) for column in select_columns)
            order_column = "updated_at" if "updated_at" in schema_fields else "id" if "id" in schema_fields else None
            order_sql = f" ORDER BY {safe_identifier(order_column)} DESC" if order_column else ""
            requested_limit = max(1, min(int(top_k or 5), 50))
            fetch_limit = max(requested_limit, min(50, max(20, requested_limit * 6)))
            sql = f"SELECT {select_sql} FROM {safe_table} WHERE {where_sql}{order_sql} LIMIT {fetch_limit}"
            rows = _fetchall_dict(cursor, sql, params)

            ranked: list[tuple[float, tuple[str, str, str], Any]] = []
            for row in rows:
                match_reason, score, score_breakdown = score_row(
                    row,
                    terms,
                    filters,
                    unit_type_hints=unit_type_hints,
                )
                hit = hit_from_row(
                    row,
                    match_reason=match_reason,
                    score=score,
                    score_breakdown=score_breakdown,
                )
                ranked.append((float(score), _stable_row_key(row), hit))
            ranked.sort(key=lambda item: (-item[0], item[1]))
            hits = [item[2] for item in ranked[:requested_limit]]

            return KnowledgeUnitSearchResult(
                query=query,
                unit_type_filter=filters,
                status="ok",
                enabled=True,
                hits=hits,
                schema_fields=sorted(schema_fields),
                query_terms=terms,
                query_debug_info=query_debug_info,
                db_connection_opened=db_connection_opened,
            ).to_dict()
        except Exception as exc:
            return KnowledgeUnitSearchResult(
                query=query,
                unit_type_filter=filters,
                status="error",
                enabled=True,
                error_type=type(exc).__name__,
                error=_sanitize_error(exc),
                query_terms=terms,
                query_debug_info=query_debug_info,
                db_connection_opened=db_connection_opened,
            ).to_dict()
        finally:
            if connection is not None:
                _closed(connection)


def search_knowledge_units_shadow(
    query: str,
    *,
    unit_types: list[str] | tuple[str, ...] | set[str] | None = None,
    top_k: int = 5,
    enabled: bool = False,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    adapter = KnowledgeUnitsRetrievalAdapter(cfg=cfg, enabled=enabled)
    return adapter.search(query, unit_types=unit_types, top_k=top_k)


__all__ = [
    "KnowledgeUnitsRetrievalAdapter",
    "TARGET_TABLE",
    "search_knowledge_units_shadow",
    "_execute_select",
    "_sanitize_error",
]
