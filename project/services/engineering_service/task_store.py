"""Task checkpoints in the existing engineering SQLite ledger, never the RAG DB."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

from .store import EngineeringStore, RunConflict, encode, identifier, now
from .result_identity import assert_task_result


TERMINAL = {"completed", "blocked", "failed", "incomplete", "cancelled", "interrupted"}


class TaskStore(EngineeringStore):
    def _tables(self, con):
        con.executescript("""
            CREATE TABLE IF NOT EXISTS engineering_tasks (
                task_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, snapshot TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0, retried_by TEXT);
            CREATE TABLE IF NOT EXISTS engineering_task_checkpoints (
                task_id TEXT NOT NULL, revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY(task_id, revision));
        """)

    def save_task(self, snapshot, *, parent_revision=None):
        item = deepcopy(snapshot)
        assert_task_result(item)
        identifier(item["task_id"])
        with self.connection() as con:
            self._tables(con)
            old = con.execute("SELECT revision,snapshot FROM engineering_tasks WHERE task_id=?", (item["task_id"],)).fetchone()
            revision = old["revision"] if old else 0
            if item.get("revision", 0) != revision:
                raise RunConflict("Task revision changed; refresh the task")
            if old:
                previous = json.loads(old["snapshot"])
                fixed = ("request", "request_fingerprint", "scope", "planner_version", "parent_task_id", "parent_revision", "continuation", "query", "identity_version", "session_id")
                if any(previous.get(key) != item.get(key) for key in fixed):
                    raise RunConflict("A task's request and planner version are immutable")
                plan_fields = ("step_id", "title", "depends_on", "dependency_policy", "input_bindings")
                if [[s.get(k) for k in plan_fields] for s in previous["steps"]] != [[s.get(k) for k in plan_fields] for s in item["steps"]]:
                    raise RunConflict("The declared task plan is immutable")
                if previous.get("input_fingerprint") and previous["input_fingerprint"] != item.get("input_fingerprint"):
                    raise RunConflict("Structured task input fingerprint changed")
            report = ((item.get("result") or {}).get("metadata") or {}).get("report") or {}
            if report.get("generated") and report.get("content") and item.get("report", {}).get("content_sha256"):
                if hashlib.sha256(report["content"].encode()).hexdigest() != item["report"]["content_sha256"]:
                    raise ValueError("Task report hash does not match its content")
            parent = item.get("parent_task_id")
            if parent_revision is not None:
                row = con.execute("SELECT * FROM engineering_tasks WHERE task_id=?", (identifier(parent),)).fetchone()
                continuation = item.get("continuation") is not None
                allowed = TERMINAL if continuation else TERMINAL - {"completed"}
                if not row or row["revision"] != parent_revision or (not continuation and row["retried_by"]) or row["status"] not in allowed:
                    raise RunConflict("Parent task changed or has already been retried")
                if continuation:
                    parent_snapshot = json.loads(row["snapshot"])
                    if parent_snapshot["request"]["session_id"] != item["request"]["session_id"]:
                        raise RunConflict("Continuation must belong to the same conversation")
                else:
                    con.execute("UPDATE engineering_tasks SET retried_by=? WHERE task_id=?", (item["task_id"], parent))
            item.update(revision=revision + 1, updated_at=now())
            text = encode(item)
            con.execute("""INSERT INTO engineering_tasks(task_id,revision,status,created_at,updated_at,snapshot)
                VALUES(?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET
                revision=excluded.revision,status=excluded.status,updated_at=excluded.updated_at,snapshot=excluded.snapshot""",
                (item["task_id"], item["revision"], item["status"], item["created_at"], item["updated_at"], text))
            con.execute("INSERT INTO engineering_task_checkpoints VALUES(?,?,?)", (item["task_id"], item["revision"], text))
        snapshot.update(revision=item["revision"], updated_at=item["updated_at"])
        return item

    def read_task(self, task_id):
        with self.connection() as con:
            self._tables(con)
            row = con.execute("SELECT * FROM engineering_tasks WHERE task_id=?", (identifier(task_id),)).fetchone()
            if row is None:
                raise KeyError("Task not found")
        return {**json.loads(row["snapshot"]), "cancel_requested": bool(row["cancel_requested"]), "retried_by": row["retried_by"]}

    def get_task(self, task_id):
        item = self.read_task(task_id)
        # An OS lease covers both queued and running tasks across processes. A
        # different live worker is never inferred dead from local thread state.
        if item["status"] not in TERMINAL:
            try:
                with self.lock(task_id):
                    item = self.read_task(task_id)
                    if item["status"] not in TERMINAL:
                        item["status"] = "interrupted"
                        item["error"] = {"code": "TASK_INTERRUPTED", "message": "执行进程已结束，任务未自动重放；可查看已保存结果并创建关联重试。"}
                        for step in item["steps"]:
                            if step["status"] in {"pending", "running"}:
                                step.update(status="interrupted", finished_at=now())
                                item["events"].append({"sequence": len(item["events"]) + 1, "step_id": step["step_id"],
                                    "title": step["title"], "status": "interrupted", "at": now(), "detail": "进程未持有执行锁，未继续执行。"})
                        self.save_task(item)
            except RunConflict:
                pass
        item["recoverable"] = item["status"] in TERMINAL - {"completed"} and not item.get("retried_by")
        return item

    def request_cancel(self, task_id, revision):
        with self.connection() as con:
            self._tables(con)
            row = con.execute("SELECT * FROM engineering_tasks WHERE task_id=?", (identifier(task_id),)).fetchone()
            if row is None:
                raise KeyError("Task not found")
            if row["revision"] != revision or row["status"] in TERMINAL:
                raise RunConflict("Task changed or finished; refresh before cancelling")
            con.execute("UPDATE engineering_tasks SET cancel_requested=1 WHERE task_id=?", (task_id,))
        return self.get_task(task_id)

    @staticmethod
    def summary(item):
        steps = item["steps"]
        return {**{k: item.get(k) for k in ("task_id", "status", "revision", "query", "created_at", "updated_at",
                    "parent_task_id", "retried_by", "recoverable", "cancel_requested", "error")},
                "step_summary": {"total": len(steps), "completed": sum(s["status"] == "completed" for s in steps),
                                 "failed": sum(s["status"] in {"failed", "blocked", "interrupted"} for s in steps)},
                "current_step": next((s["title"] for s in steps if s["status"] == "running"), None)}

    def list_tasks(self, limit=30, offset=0):
        with self.connection() as con:
            self._tables(con)
            total = con.execute("SELECT COUNT(*) FROM engineering_tasks").fetchone()[0]
            ids = [row[0] for row in con.execute("SELECT task_id FROM engineering_tasks ORDER BY created_at DESC,task_id LIMIT ? OFFSET ?",
                   (min(100, max(1, limit)), max(0, offset)))]
        return {"tasks": [self.summary(self.get_task(key)) for key in ids], "total": total}

    def recent_session_task(self, session_id):
        """Resolve within persisted request ownership, never global drawer selection."""
        with self.connection() as con:
            self._tables(con)
            row = con.execute("""SELECT task_id FROM engineering_tasks
                WHERE json_extract(snapshot, '$.request.session_id') = ?
                ORDER BY created_at DESC,task_id DESC LIMIT 1""", (session_id,)).fetchone()
        return self.get_task(row[0]) if row else None


def read_only_tasks(path, task_id=None, limit=30, offset=0):
    """Admin projection: no schema creation, recovery, locks or writable connection."""
    location = Path(path).resolve()
    if not location.is_file():
        if task_id:
            raise KeyError("Task not found")
        return {"tasks": [], "total": 0, "store_available": False}
    con = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='engineering_tasks'").fetchone():
            if task_id:
                raise KeyError("Task not found")
            return {"tasks": [], "total": 0, "store_available": False}
        def project(row):
            item = {**json.loads(row["snapshot"]), "cancel_requested": bool(row["cancel_requested"]), "retried_by": row["retried_by"]}
            item["recoverable"] = item["status"] in TERMINAL - {"completed"} and not row["retried_by"]
            item.pop("request", None)
            return item
        if task_id:
            row = con.execute("SELECT * FROM engineering_tasks WHERE task_id=?", (identifier(task_id),)).fetchone()
            if not row:
                raise KeyError("Task not found")
            return project(row)
        total = con.execute("SELECT COUNT(*) FROM engineering_tasks").fetchone()[0]
        rows = con.execute("SELECT * FROM engineering_tasks ORDER BY created_at DESC,task_id LIMIT ? OFFSET ?",
                           (min(100, max(1, limit)), max(0, offset))).fetchall()
        return {"tasks": [TaskStore.summary(project(row)) for row in rows], "total": total, "store_available": True}
    finally:
        con.close()
