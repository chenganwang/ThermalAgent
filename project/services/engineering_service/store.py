"""SQLite snapshots and immutable artifacts for a single-user local workstation.

Each checkpoint commits its run, steps, variables, evidence and timeline together.
OS file locks distinguish an active execution from an abandoned checkpoint after
a crash. Recovery is explicit and creates a child run; nothing runs on startup.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", value):
        raise ValueError("Invalid engineering identifier")
    return value


def encode(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(text.encode("utf-8")) > 10_000_000:
        raise ValueError("Engineering checkpoint exceeds 10 MB")
    return text


class RunConflict(ValueError):
    pass


class RunLock:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        try:
            if path.stat().st_size == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RunConflict("Run is currently executing") from exc

    def close(self):
        if not self.file.closed:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class EngineeringStore:
    def __init__(self, path: Path | str):
        # Lazy initialization lets API startup and ordinary QA survive disk faults.
        self.path = Path(path).resolve()

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA journal_mode=WAL")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported engineering database version")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    description TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects,
                    parent_run_id TEXT REFERENCES runs, resumed_by TEXT REFERENCES runs,
                    revision INTEGER NOT NULL, status TEXT NOT NULL, tool_name TEXT NOT NULL,
                    tool_version TEXT NOT NULL, model_version TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    receipt TEXT NOT NULL, request TEXT NOT NULL, calculation_result TEXT,
                    report_sha256 TEXT);
                CREATE INDEX IF NOT EXISTS runs_project_time ON runs(project_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS snapshots (
                    run_id TEXT REFERENCES runs, revision INTEGER, at TEXT NOT NULL,
                    receipt TEXT NOT NULL, PRIMARY KEY(run_id, revision));
                CREATE TABLE IF NOT EXISTS steps (
                    run_id TEXT, revision INTEGER, step_id TEXT, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, revision, step_id),
                    FOREIGN KEY(run_id, revision) REFERENCES snapshots);
                CREATE TABLE IF NOT EXISTS variables (
                    run_id TEXT, revision INTEGER, ordinal INTEGER, name TEXT NOT NULL,
                    role TEXT, unit TEXT, source TEXT, step_id TEXT, value TEXT NOT NULL,
                    PRIMARY KEY(run_id, revision, ordinal),
                    FOREIGN KEY(run_id, revision) REFERENCES snapshots);
                CREATE TABLE IF NOT EXISTS evidence (
                    run_id TEXT, revision INTEGER, ordinal INTEGER, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, revision, ordinal),
                    FOREIGN KEY(run_id, revision) REFERENCES snapshots);
                CREATE TABLE IF NOT EXISTS timeline (
                    run_id TEXT, revision INTEGER, sequence INTEGER, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, revision, sequence),
                    FOREIGN KEY(run_id, revision) REFERENCES snapshots);
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs,
                    kind TEXT NOT NULL, media_type TEXT NOT NULL, sha256 TEXT NOT NULL,
                    content BLOB NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(run_id, kind, sha256));
                PRAGMA user_version=1;
            """)
            con.execute("INSERT OR IGNORE INTO projects VALUES ('local', '本地工程', '', ?)", (now(),))
            con.commit()
            with con:
                yield con
        finally:
            con.close()

    def lock(self, run_id):
        return RunLock(self.path.parent / "locks" / (identifier(run_id) + ".lock"))

    def active(self, run_id):
        try:
            with self.lock(run_id):
                return False
        except RunConflict:
            return True

    def create_project(self, title, description=""):
        project = dict(project_id="project_" + uuid4().hex, title=title,
                       description=description, created_at=now())
        with self.connection() as con:
            con.execute("INSERT INTO projects VALUES (:project_id,:title,:description,:created_at)", project)
        return project

    def projects(self):
        with self.connection() as con:
            return [dict(row) for row in con.execute("SELECT * FROM projects ORDER BY created_at DESC")]

    def project_exists(self, project_id):
        with self.connection() as con:
            return con.execute("SELECT 1 FROM projects WHERE project_id=?", (identifier(project_id),)).fetchone() is not None

    def save(self, receipt, request, *, project_id="local", result=None, report=None,
             parent_run_id=None, recovery_revision=None):
        from .result_identity import assert_run_result
        assert_run_result(receipt, result, require_identity=True)
        receipt = deepcopy(receipt)
        receipt.setdefault("model_version", "deterministic-formula-v2.1")
        run_id = identifier(receipt["run_id"])
        identifier(project_id)
        encoded = encode(receipt)
        with self.connection() as con:
            old = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if old and (any(json.loads(old["receipt"]).get(key) != receipt.get(key)
                            for key in ("input_snapshot", "input_fingerprint", "calculation_fingerprint", "design_criteria", "tool_name", "tool_version", "model_version", "task_id", "session_id", "request_fingerprint"))
                        or old["project_id"] != project_id):
                raise RunConflict("A run's inputs and project are immutable")
            revision = old["revision"] + 1 if old else 1
            if recovery_revision is not None:
                parent = con.execute("SELECT * FROM runs WHERE run_id=?", (parent_run_id,)).fetchone()
                if (not parent or parent["revision"] != recovery_revision or parent["resumed_by"]
                        or parent["status"] == "completed"):
                    raise RunConflict("Recovery state changed; refresh the run")
            report_hash = hashlib.sha256(report.encode("utf-8")).hexdigest() if report else (old["report_sha256"] if old else None)
            if report and receipt.get("report", {}).get("content_sha256") != report_hash:
                raise ValueError("Report hash does not match receipt")
            con.execute("""INSERT INTO runs
                (run_id,project_id,parent_run_id,revision,status,tool_name,tool_version,model_version,
                 created_at,updated_at,receipt,request,calculation_result,report_sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET revision=excluded.revision,status=excluded.status,
                updated_at=excluded.updated_at,receipt=excluded.receipt,
                calculation_result=COALESCE(excluded.calculation_result,runs.calculation_result),
                report_sha256=excluded.report_sha256""",
                (run_id, project_id, parent_run_id, revision,
                 "running" if receipt["status"] == "completed" and not receipt.get("finished_at") else receipt["status"], receipt["tool_name"],
                 receipt["tool_version"], receipt.get("model_version", "deterministic-formula-v2.1"),
                 receipt["created_at"], now(), encoded, encode(request),
                 encode(result) if result is not None else None, report_hash))
            if recovery_revision is not None:
                con.execute("UPDATE runs SET resumed_by=? WHERE run_id=?", (run_id, parent_run_id))
            con.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (run_id, revision, now(), encoded))
            for step in receipt.get("steps", []):
                con.execute("INSERT INTO steps VALUES (?,?,?,?)", (run_id, revision, step["step_id"], encode(step)))
            for i, var in enumerate(receipt.get("variables", [])):
                con.execute("INSERT INTO variables VALUES (?,?,?,?,?,?,?,?,?)",
                            (run_id, revision, i, var["name"], var.get("role"), var.get("unit"),
                             var.get("source"), var.get("step_id"), encode(var.get("value"))))
            for table, values in (("evidence", receipt.get("evidence", [])), ("timeline", receipt.get("events", []))):
                for i, value in enumerate(values):
                    con.execute(f"INSERT INTO {table} VALUES (?,?,?,?)", (run_id, revision, i, encode(value)))
            for kind, media_type, content in (
                    ("report", "text/markdown", report.encode("utf-8") if report else None),
                    ("calculation", "application/json", encode(result).encode("utf-8") if result is not None else None)):
                if content is not None:
                    con.execute("INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?,?)",
                                ("artifact_" + uuid4().hex, run_id, kind, media_type,
                                 hashlib.sha256(content).hexdigest(), content, now()))
        return {"saved": True, "run_id": run_id, "project_id": project_id, "revision": revision,
                "report_sha256": report_hash}

    def _summary(self, row):
        keys = ("run_id", "project_id", "parent_run_id", "resumed_by", "revision", "status", "tool_name",
                "tool_version", "model_version", "created_at", "updated_at", "report_sha256")
        result = {key: row[key] for key in keys}
        result["active"] = self.active(row["run_id"])
        result["recoverable"] = not result["active"] and row["status"] != "completed" and not row["resumed_by"]
        return result

    def list_runs(self, project_id=None, limit=30, offset=0):
        where, args = ("WHERE project_id=?", [identifier(project_id)]) if project_id else ("", [])
        with self.connection() as con:
            total = con.execute(f"SELECT COUNT(*) FROM runs {where}", args).fetchone()[0]
            rows = con.execute(f"SELECT * FROM runs {where} ORDER BY created_at DESC,run_id LIMIT ? OFFSET ?",
                               [*args, min(100, max(1, limit)), max(0, offset)]).fetchall()
        return {"runs": [self._summary(row) for row in rows], "total": total}

    def get(self, run_id):
        with self.connection() as con:
            row = con.execute("SELECT * FROM runs WHERE run_id=?", (identifier(run_id),)).fetchone()
            if not row:
                raise KeyError("Engineering run not found")
            artifacts = [dict(item) for item in con.execute(
                "SELECT artifact_id,kind,media_type,sha256,created_at FROM artifacts WHERE run_id=? ORDER BY created_at",
                (run_id,))]
        from .result_identity import assert_run_result
        receipt = json.loads(row["receipt"])
        result = json.loads(row["calculation_result"]) if row["calculation_result"] else None
        assert_run_result(receipt, result, require_identity=True)
        if receipt["run_id"] != run_id:
            raise ValueError("Stored Run identity mismatch")
        return {**self._summary(row), "receipt": receipt, "request": json.loads(row["request"]),
                "calculation_result": result, "artifacts": artifacts}

    def artifact(self, run_id, artifact_id):
        with self.connection() as con:
            row = con.execute("SELECT * FROM artifacts WHERE run_id=? AND artifact_id=?",
                              (identifier(run_id), identifier(artifact_id))).fetchone()
            if not row:
                raise KeyError("Engineering artifact not found")
            if hashlib.sha256(row["content"]).hexdigest() != row["sha256"]:
                raise ValueError("Engineering artifact integrity check failed")
            return dict(row)

    def compare(self, run_ids):
        runs = [self.get(run_id) for run_id in run_ids]
        warnings = []
        if len({(r["tool_name"], r["tool_version"], r["model_version"]) for r in runs}) > 1:
            warnings.append("工具或模型版本不同，数值差不作为等价模型对比。")
        if any(r["status"] != "completed" or r["receipt"].get("validation", {}).get("status") != "passed" for r in runs):
            warnings.append("包含未完成或未通过物理检查的方案；不计算设计差值。")
        maps = [{v["name"]: v for v in r["receipt"].get("variables", []) if v.get("role") == "output"} for r in runs]
        rows = []
        for name in sorted(set().union(*(m.keys() for m in maps))):
            variables = [m.get(name, {}) for m in maps]
            units = [v.get("unit") for v in variables]
            values = [v.get("value") for v in variables]
            comparable = bool(units[0]) and len(set(units)) == 1
            if not comparable:
                warnings.append(f"{name}: 单位缺失或不一致。")
            numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)
            delta = values[1] - values[0] if len(values) == 2 and comparable and numeric and not warnings else None
            if delta is not None and not math.isfinite(delta):
                warnings.append(f"{name}: 差值超出有限数值范围。")
                delta = None
            rows.append({"name": name, "unit": units[0] if comparable else None, "values": values, "delta": delta})
        return {"runs": [{k: r[k] for k in ("run_id", "tool_name", "status", "project_id")} for r in runs],
                "variables": [{**row, "delta": None} for row in rows] if warnings else rows,
                "compatible": not warnings, "warnings": list(dict.fromkeys(warnings))}
