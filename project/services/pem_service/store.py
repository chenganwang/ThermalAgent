"""Append-only PEM records in the existing EngineeringStore SQLite database."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json

from services.engineering_service.store import encode, identifier
from .parameters import canonical_hash


class PEMStore:
    def __init__(self, engineering_store):
        self.engineering = engineering_store

    @contextmanager
    def connection(self):
        with self.engineering.connection() as con:
            # Additive tables; existing schema/version and engineering rows are preserved.
            con.executescript("""
                CREATE TABLE IF NOT EXISTS pem_studies (
                    study_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects,
                    parent_study_id TEXT REFERENCES pem_studies, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pem_batches (
                    batch_id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES pem_studies,
                    run_id TEXT NOT NULL REFERENCES runs, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pem_candidates (
                    candidate_id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES pem_studies,
                    batch_id TEXT NOT NULL REFERENCES pem_batches, payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pem_imports (
                    import_id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES pem_studies,
                    run_id TEXT NOT NULL REFERENCES runs, created_at TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, content BLOB NOT NULL,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pem_results (
                    result_id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES pem_studies,
                    import_id TEXT NOT NULL REFERENCES pem_imports,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS pem_candidates_study ON pem_candidates(study_id);
                CREATE INDEX IF NOT EXISTS pem_results_study ON pem_results(study_id);
            """)
            yield con

    @staticmethod
    def unpack(row):
        payload = json.loads(row["payload"])
        if canonical_hash(payload) != row["payload_sha256"]:
            raise ValueError("PEM record integrity check failed")
        return payload

    def create_study(self, study):
        with self.connection() as con:
            con.execute("INSERT INTO pem_studies VALUES (?,?,?,?,?,?)",
                        (study["study_id"], study["project_id"], study.get("parent_study_id"), study["created_at"],
                         encode(study), canonical_hash(study)))
        return study

    def studies(self, project_id=None):
        where, args = ("WHERE project_id=?", [identifier(project_id)]) if project_id else ("", [])
        with self.connection() as con:
            rows = con.execute(f"SELECT * FROM pem_studies {where} ORDER BY created_at DESC,study_id", args).fetchall()
            return [self.unpack(r) for r in rows]

    def get_study(self, study_id):
        with self.connection() as con:
            row = con.execute("SELECT * FROM pem_studies WHERE study_id=?", (identifier(study_id),)).fetchone()
            if row is None:
                raise KeyError("PEM study not found")
            return self.unpack(row)

    def save_batch(self, batch):
        with self.connection() as con:
            con.execute("INSERT INTO pem_batches VALUES (?,?,?,?,?,?)",
                        (batch["batch_id"], batch["study_id"], batch["run_id"], batch["created_at"],
                         encode(batch), canonical_hash(batch)))
            for candidate in batch["candidates"]:
                con.execute("INSERT INTO pem_candidates VALUES (?,?,?,?,?)",
                            (candidate["candidate_id"], candidate["study_id"], candidate["batch_id"],
                             encode(candidate), canonical_hash(candidate)))

    def candidates(self, study_id):
        self.get_study(study_id)
        with self.connection() as con:
            return [self.unpack(row) for row in con.execute(
                "SELECT * FROM pem_candidates WHERE study_id=? ORDER BY rowid", (identifier(study_id),))]

    def batches(self, study_id):
        with self.connection() as con:
            return [self.unpack(row) for row in con.execute(
                "SELECT * FROM pem_batches WHERE study_id=? ORDER BY created_at,batch_id", (identifier(study_id),))]

    def save_import(self, imported, content):
        raw = content.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != imported["source"]["sha256"]:
            raise ValueError("Import source hash mismatch")
        with self.connection() as con:
            con.execute("INSERT INTO pem_imports VALUES (?,?,?,?,?,?,?,?)",
                        (imported["import_id"], imported["study_id"], imported["run_id"], imported["created_at"], digest,
                         raw, encode(imported), canonical_hash(imported)))
            for result in imported["records"]:
                con.execute("INSERT INTO pem_results VALUES (?,?,?,?,?)",
                            (result["result_id"], imported["study_id"], imported["import_id"],
                             encode(result), canonical_hash(result)))

    def results(self, study_id):
        self.get_study(study_id)
        with self.connection() as con:
            return [self.unpack(row) for row in con.execute(
                "SELECT * FROM pem_results WHERE study_id=? ORDER BY rowid", (identifier(study_id),))]

    def imports(self, study_id):
        with self.connection() as con:
            records = [self.unpack(row) for row in con.execute(
                "SELECT * FROM pem_imports WHERE study_id=? ORDER BY created_at,import_id", (identifier(study_id),))]
        return [{k: v for k, v in record.items() if k != "records"} for record in records]

    def source(self, study_id, import_id):
        self.get_study(study_id)
        with self.connection() as con:
            row = con.execute("SELECT * FROM pem_imports WHERE study_id=? AND import_id=?",
                              (identifier(study_id), identifier(import_id))).fetchone()
            if row is None:
                raise KeyError("PEM import source not found")
            payload = self.unpack(row)
            content = bytes(row["content"])
            if hashlib.sha256(content).hexdigest() != row["source_sha256"] or payload["source"]["sha256"] != row["source_sha256"]:
                raise ValueError("PEM source integrity check failed")
            return {"content": content, "source": payload["source"], "sha256": row["source_sha256"]}
