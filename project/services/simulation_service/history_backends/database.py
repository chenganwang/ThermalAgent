from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import sqlite3

from .base import SimulationHistoryBackend, coerce_history_record
from ..schema import SimulationHistoryRecord, model_to_dict


REQUIRED_TABLES = ["simulation_runs", "simulation_logs", "simulation_models", "simulation_tools"]
REQUIRED_RUN_INDEXES = [
    "idx_sim_runs_tool",
    "idx_sim_runs_adapter",
    "idx_sim_runs_status",
    "idx_sim_runs_created",
    "idx_sim_runs_trace",
]
REQUIRED_RUN_COLUMNS = [
    "run_id",
    "history_id",
    "task_id",
    "tool_name",
    "adapter_name",
    "backend_type",
    "status",
    "is_mock",
    "request_json",
    "result_json",
    "trace_id",
    "created_at",
]


class DatabaseHistoryBackend(SimulationHistoryBackend):
    """SQLite/DB-API backed Simulation History repository.

    Phase 3 deliberately keeps production MySQL migration execution outside the
    runtime. This backend accepts SQLite URLs for isolated tests and local
    opt-in usage. Unsupported or disabled database URLs are reported as
    controlled unavailable instead of failing application import/startup.
    """

    def __init__(
        self,
        *,
        database_url: str,
        enabled: bool,
        auto_create: bool = False,
        allow_clear_for_test: bool = False,
    ) -> None:
        self.database_url = str(database_url or "")
        self.enabled = bool(enabled)
        self.auto_create = bool(auto_create)
        self.allow_clear_for_test = bool(allow_clear_for_test)
        self._reason = self._availability_reason()
        if self._reason == "available" and self.auto_create:
            self._ensure_schema()

    def health_check(self) -> dict[str, object]:
        migration = self.migration_status()
        return {
            "backend": "database",
            "available": bool(migration["ready"]),
            "reason": "available" if migration["ready"] else migration["reason"],
            "database_url_scheme": _scheme(self.database_url),
            "auto_create": self.auto_create,
            "migration": migration,
        }

    def required_tables(self) -> list[str]:
        return list(REQUIRED_TABLES)

    def required_indexes(self) -> list[str]:
        return list(REQUIRED_RUN_INDEXES)

    def is_ready(self) -> bool:
        return bool(self.migration_status()["ready"])

    def explain_unavailable_reason(self) -> str:
        status = self.migration_status()
        if status["ready"]:
            return "available"
        missing_tables = ",".join(status.get("missing_tables") or [])
        missing_indexes = ",".join(status.get("missing_indexes") or [])
        parts = [str(status.get("reason") or "database_unavailable")]
        if missing_tables:
            parts.append(f"missing_tables={missing_tables}")
        if missing_indexes:
            parts.append(f"missing_indexes={missing_indexes}")
        return ": ".join(parts)

    def migration_status(self) -> dict[str, object]:
        if self._reason != "available":
            return {
                "ready": False,
                "reason": self._reason,
                "required_tables": self.required_tables(),
                "required_indexes": self.required_indexes(),
                "missing_tables": self.required_tables(),
                "missing_indexes": self.required_indexes(),
            }
        try:
            conn = self._connect(skip_ready_check=True)
        except Exception as exc:
            return {
                "ready": False,
                "reason": f"database_connection_failed:{type(exc).__name__}",
                "required_tables": self.required_tables(),
                "required_indexes": self.required_indexes(),
                "missing_tables": self.required_tables(),
                "missing_indexes": self.required_indexes(),
            }
        try:
            return self.check_schema(conn)
        finally:
            conn.close()

    def check_schema(self, conn=None) -> dict[str, object]:
        close = False
        if conn is None:
            conn = self._connect(skip_ready_check=True)
            close = True
        try:
            tables = _sqlite_tables(conn)
            missing_tables = [table for table in self.required_tables() if table not in tables]
            run_columns = _sqlite_columns(conn, "simulation_runs") if "simulation_runs" in tables else set()
            missing_columns = [column for column in REQUIRED_RUN_COLUMNS if column not in run_columns]
            run_indexes = _sqlite_indexes(conn, "simulation_runs") if "simulation_runs" in tables else set()
            missing_indexes = [index for index in self.required_indexes() if index not in run_indexes]
            ready = not missing_tables and not missing_columns and not missing_indexes
            return {
                "ready": ready,
                "reason": "ready" if ready else "database_schema_not_ready",
                "required_tables": self.required_tables(),
                "required_indexes": self.required_indexes(),
                "present_tables": sorted(tables),
                "missing_tables": missing_tables,
                "missing_columns": missing_columns,
                "missing_indexes": missing_indexes,
            }
        finally:
            if close:
                conn.close()

    def append(self, record: SimulationHistoryRecord | dict) -> SimulationHistoryRecord:
        self._require_available()
        item = coerce_history_record(record)
        payload = item.result or {}
        conn = self._connect()
        try:
            if self.auto_create:
                self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO simulation_runs (
                  run_id, history_id, task_id, tool_name, adapter_name, backend_type, status, is_mock,
                  user_query, request_json, result_json, error_json, warning_json, trace_id,
                  software, software_version, model_version, elapsed_ms, created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.run_id,
                    item.history_id,
                    item.task_id,
                    _text(payload.get("tool_name") or item.request.get("tool_name") or item.metadata.get("tool_name")),
                    _text(payload.get("adapter_name") or item.request.get("adapter_name") or item.metadata.get("adapter_name")),
                    _text(payload.get("backend_type") or payload.get("adapter_name") or item.metadata.get("adapter_name")),
                    item.status,
                    1 if bool(payload.get("is_mock", payload.get("mocked", False))) else 0,
                    item.user_query,
                    _json(item.request),
                    _json(payload),
                    _json(item.error),
                    _json(payload.get("warnings") or []),
                    item.trace_id or _text(payload.get("trace_id")),
                    _text(payload.get("software")),
                    _text(payload.get("software_version")),
                    _text(payload.get("model_version")),
                    payload.get("elapsed_ms"),
                    item.created_at,
                    payload.get("started_at"),
                    payload.get("finished_at"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return item

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        tool_name: str | None = None,
        adapter_name: str | None = None,
        trace_id: str | None = None,
        is_mock: bool | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> list[SimulationHistoryRecord]:
        self._require_available()
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("status", status),
            ("tool_name", tool_name),
            ("adapter_name", adapter_name),
            ("trace_id", trace_id),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        if is_mock is not None:
            clauses.append("is_mock = ?")
            params.append(1 if is_mock else 0)
        if created_after:
            clauses.append("created_at >= ?")
            params.append(created_after)
        if created_before:
            clauses.append("created_at <= ?")
            params.append(created_before)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(min(int(limit or 50), 500), 0)
        safe_offset = max(int(offset or 0), 0)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT history_id, run_id, task_id, user_query, request_json, result_json, status,
                       error_json, created_at, trace_id, tool_name, adapter_name
                FROM simulation_runs
                {where}
                ORDER BY created_at ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (*params, safe_limit, safe_offset),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_record(row) for row in rows]

    def get(self, history_id_or_run_id: str) -> SimulationHistoryRecord | None:
        self._require_available()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT history_id, run_id, task_id, user_query, request_json, result_json, status,
                       error_json, created_at, trace_id, tool_name, adapter_name
                FROM simulation_runs
                WHERE run_id = ? OR history_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (history_id_or_run_id, history_id_or_run_id),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_record(row) if row else None

    def get_by_history_id(self, history_id: str) -> SimulationHistoryRecord | None:
        return self.get(history_id)

    def clear_for_test(self) -> None:
        self._require_available()
        if not self.allow_clear_for_test:
            raise RuntimeError("database_clear_for_test_not_allowed")
        conn = self._connect()
        try:
            conn.execute("DELETE FROM simulation_runs")
            conn.commit()
        finally:
            conn.close()

    def _availability_reason(self) -> str:
        if not self.enabled:
            return "database_backend_disabled"
        if not self.database_url:
            return "database_url_missing"
        if not self.database_url.startswith("sqlite:///") and self.database_url != "sqlite:///:memory:":
            return "unsupported_database_url"
        return "available"

    def _require_available(self) -> None:
        if self._reason != "available":
            raise RuntimeError(self._reason)
        status = self.migration_status()
        if not status["ready"]:
            raise RuntimeError(f"database_schema_not_ready: {self.explain_unavailable_reason()}")

    def _connect(self, *, skip_ready_check: bool = False):
        if self._reason != "available":
            raise RuntimeError(self._reason)
        path = _sqlite_path(self.database_url)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn=None) -> None:
        close = False
        if conn is None:
            conn = self._connect()
            close = True
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL UNIQUE,
                  history_id TEXT,
                  task_id TEXT NOT NULL,
                  tool_name TEXT NOT NULL,
                  adapter_name TEXT NOT NULL,
                  backend_type TEXT,
                  status TEXT NOT NULL,
                  is_mock INTEGER DEFAULT 0,
                  user_query TEXT,
                  request_json TEXT NOT NULL,
                  result_json TEXT NOT NULL,
                  error_json TEXT,
                  warning_json TEXT,
                  trace_id TEXT,
                  software TEXT,
                  software_version TEXT,
                  model_version TEXT,
                  elapsed_ms INTEGER,
                  created_at TEXT,
                  started_at TEXT,
                  finished_at TEXT
                )
                """
            )
            for statement in (
                "CREATE INDEX IF NOT EXISTS idx_sim_runs_tool ON simulation_runs(tool_name)",
                "CREATE INDEX IF NOT EXISTS idx_sim_runs_adapter ON simulation_runs(adapter_name)",
                "CREATE INDEX IF NOT EXISTS idx_sim_runs_status ON simulation_runs(status)",
                "CREATE INDEX IF NOT EXISTS idx_sim_runs_created ON simulation_runs(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_sim_runs_trace ON simulation_runs(trace_id)",
            ):
                conn.execute(statement)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL,
                  level TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  message TEXT,
                  payload_json TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for statement in (
                "CREATE INDEX IF NOT EXISTS idx_sim_logs_run_id ON simulation_logs(run_id)",
                "CREATE INDEX IF NOT EXISTS idx_sim_logs_level ON simulation_logs(level)",
                "CREATE INDEX IF NOT EXISTS idx_sim_logs_created ON simulation_logs(created_at)",
            ):
                conn.execute(statement)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_models (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  model_id TEXT NOT NULL UNIQUE,
                  model_name TEXT NOT NULL,
                  model_type TEXT,
                  adapter_name TEXT,
                  version TEXT,
                  metadata_json TEXT,
                  enabled INTEGER DEFAULT 1,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_models_adapter ON simulation_models(adapter_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_models_enabled ON simulation_models(enabled)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_tools (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tool_name TEXT NOT NULL,
                  adapter_name TEXT NOT NULL,
                  category TEXT,
                  description TEXT,
                  input_schema_json TEXT,
                  output_schema_json TEXT,
                  enabled INTEGER DEFAULT 1,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(tool_name, adapter_name)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_tools_category ON simulation_tools(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_tools_enabled ON simulation_tools(enabled)")
            conn.commit()
        finally:
            if close:
                conn.close()


def _sqlite_path(database_url: str) -> str:
    if database_url == "sqlite:///:memory:":
        return ":memory:"
    return database_url.removeprefix("sqlite:///")


def _scheme(database_url: str) -> str:
    return database_url.split(":", 1)[0] if ":" in database_url else ""


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _loads(value: Any, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def _text(value: Any) -> str:
    return str(value or "")


def _row_to_record(row) -> SimulationHistoryRecord:
    request = _loads(row["request_json"], {})
    result = _loads(row["result_json"], {})
    error = _loads(row["error_json"], None)
    return SimulationHistoryRecord(
        history_id=str(row["history_id"]),
        run_id=str(row["run_id"]),
        task_id=str(row["task_id"]),
        user_query=row["user_query"],
        request=request,
        result=result,
        status=str(row["status"]),
        error=error,
        created_at=str(row["created_at"]),
        trace_id=row["trace_id"],
        metadata={"tool_name": row["tool_name"], "adapter_name": row["adapter_name"]},
    )


def _sqlite_tables(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _sqlite_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _sqlite_indexes(conn, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    return {str(row[1]) for row in rows}


__all__ = ["DatabaseHistoryBackend"]
