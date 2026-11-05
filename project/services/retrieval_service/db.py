from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Iterable, Optional, Sequence
import hashlib
import json

try:
    from mysql.connector import pooling  # type: ignore
except Exception:
    pooling = None  # type: ignore

from services.ingest_service.chunking.rows import ChunkInsertRow
from .config import AppConfig

_DB_CACHE: dict[tuple[str, int, str, str], "DB"] = {}
_DB_CACHE_LOCK = Lock()


def _db_cache_key(cfg: AppConfig) -> tuple[str, int, str, str]:
    return (cfg.mysql.host, int(cfg.mysql.port), cfg.mysql.user, cfg.mysql.database)


def _pool_name_for(cfg: AppConfig) -> str:
    raw = f"{cfg.mysql.host}:{cfg.mysql.port}:{cfg.mysql.user}:{cfg.mysql.database}".encode("utf-8")
    suffix = hashlib.sha1(raw).hexdigest()[:10]
    return f"rag_pool_{suffix}"


def _json_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class ChunkRecord:
    id: int
    doc_id: int
    chunk_index: int
    page_start: int | None
    page_end: int | None
    chunk_type: str
    text: str
    token_len: int | None
    section_path: str | None
    content_hash: str | None
    meta_json: str | None


@dataclass
class DB:
    pool: pooling.MySQLConnectionPool

    @classmethod
    def create(cls, cfg: AppConfig) -> "DB":
        if pooling is None:
            raise RuntimeError("mysql-connector-python is not installed. Please install it before creating DB connections.")
        key = _db_cache_key(cfg)
        cached = _DB_CACHE.get(key)
        if cached is not None:
            return cached
        with _DB_CACHE_LOCK:
            cached = _DB_CACHE.get(key)
            if cached is not None:
                return cached
            pool = pooling.MySQLConnectionPool(
                pool_name=_pool_name_for(cfg),
                pool_size=5,
                pool_reset_session=True,
                host=cfg.mysql.host,
                port=cfg.mysql.port,
                user=cfg.mysql.user,
                password=cfg.mysql.password,
                database=cfg.mysql.database,
                autocommit=False,
            )
            db = cls(pool=pool)
            db.ensure_runtime_tables()
            _DB_CACHE[key] = db
            return db

    def execute(self, sql: str, params: Optional[tuple] = None) -> int:
        conn = self.pool.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params or ())
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def executemany(self, sql: str, params: Iterable[tuple]) -> int:
        items = list(params)
        if not items:
            return 0
        conn = self.pool.get_connection()
        try:
            cur = conn.cursor()
            cur.executemany(sql, items)
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def fetchone(self, sql: str, params: Optional[tuple] = None) -> Optional[tuple]:
        conn = self.pool.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params or ())
            return cur.fetchone()
        finally:
            conn.close()

    def fetchall(self, sql: str, params: Optional[tuple] = None) -> list[tuple]:
        conn = self.pool.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params or ())
            return cur.fetchall()
        finally:
            conn.close()

    def table_exists(self, table_name: str) -> bool:
        row = self.fetchone(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = %s
            """,
            (table_name,),
        )
        return bool(row and int(row[0]) > 0)

    def column_exists(self, table_name: str, column_name: str) -> bool:
        row = self.fetchone(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
            """,
            (table_name, column_name),
        )
        return bool(row and int(row[0]) > 0)

    def _add_column_if_missing(self, table_name: str, column_name: str, ddl: str) -> None:
        if self.table_exists(table_name) and not self.column_exists(table_name, column_name):
            self.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")

    def ensure_runtime_tables(self) -> None:
        """Create additive compatibility and retrieval runtime tables.

        The authoritative project schema defines source and knowledge tables.
        Retrieval still needs FAISS/BM25 runtime metadata. The user-facing
        schema also names several structured tables that may be absent from the
        bundled schema package, so we add them without changing existing data.
        """
        self.ensure_core_compatibility_tables()
        if not self.table_exists("chunks"):
            return
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              chunk_id BIGINT NOT NULL,
              model_name VARCHAR(255) NOT NULL,
              embedding_model VARCHAR(255) NULL,
              dim INT NOT NULL,
              vector_pos BIGINT NOT NULL,
              index_name VARCHAR(128) DEFAULT 'faiss',
              index_version VARCHAR(64) NULL,
              build_id VARCHAR(64) NULL,
              content_hash CHAR(64) NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY uq_embeddings_chunk (chunk_id),
              UNIQUE KEY uq_vector_pos (vector_pos),
              CONSTRAINT fk_embed_chunk FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        self._add_column_if_missing("embeddings", "embedding_model", "embedding_model VARCHAR(255) NULL AFTER model_name")
        self._add_column_if_missing("embeddings", "index_name", "index_name VARCHAR(128) DEFAULT 'faiss' AFTER vector_pos")
        self._add_column_if_missing("embeddings", "index_version", "index_version VARCHAR(64) NULL AFTER index_name")
        self._add_column_if_missing("embeddings", "content_hash", "content_hash CHAR(64) NULL AFTER build_id")
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS retrieval_log (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              query_text TEXT NOT NULL,
              rewritten_query TEXT NULL,
              top_k INT NULL,
              topk INT NOT NULL,
              hit_count INT NULL,
              faiss_topn INT NOT NULL,
              latency_ms INT NOT NULL,
              model_name VARCHAR(255) NOT NULL,
              hit_vector_pos TEXT NULL,
              hit_chunk_ids TEXT NULL,
              result_json JSON NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        self._add_column_if_missing("retrieval_log", "rewritten_query", "rewritten_query TEXT NULL AFTER query_text")
        self._add_column_if_missing("retrieval_log", "top_k", "top_k INT NULL AFTER rewritten_query")
        self._add_column_if_missing("retrieval_log", "hit_count", "hit_count INT NULL AFTER topk")
        self._add_column_if_missing("retrieval_log", "result_json", "result_json JSON NULL AFTER hit_chunk_ids")

    def ensure_core_compatibility_tables(self) -> None:
        if not self.table_exists("documents"):
            return
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS document_sections (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              doc_id BIGINT NOT NULL,
              parent_id BIGINT NULL,
              title VARCHAR(512) NULL,
              section_path VARCHAR(1024) NOT NULL,
              level INT NULL,
              page_start INT NULL,
              page_end INT NULL,
              meta_json JSON NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_doc_section_path (doc_id, section_path(512)),
              KEY idx_doc_sections_doc (doc_id),
              KEY idx_doc_sections_parent (parent_id),
              CONSTRAINT fk_doc_sections_doc FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
              CONSTRAINT fk_doc_sections_parent FOREIGN KEY (parent_id) REFERENCES document_sections(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        if self.table_exists("chunks"):
            self._add_column_if_missing("chunks", "section_id", "section_id BIGINT NULL AFTER doc_id")

        if self.table_exists("formulas"):
            self.execute(
                """
                CREATE TABLE IF NOT EXISTS formula_variables (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  formula_id BIGINT NOT NULL,
                  variable_name VARCHAR(128) NOT NULL,
                  symbol VARCHAR(128) NULL,
                  description TEXT NULL,
                  unit VARCHAR(128) NULL,
                  default_value VARCHAR(128) NULL,
                  meta_json JSON NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE KEY uq_formula_variable (formula_id, variable_name),
                  KEY idx_formula_variables_formula (formula_id),
                  CONSTRAINT fk_formula_variables_formula FOREIGN KEY (formula_id) REFERENCES formulas(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        if self.table_exists("chunks"):
            self.execute(
                """
                CREATE TABLE IF NOT EXISTS cases (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  case_code VARCHAR(128) UNIQUE,
                  title VARCHAR(512) NOT NULL,
                  case_type VARCHAR(128) NULL,
                  summary TEXT NULL,
                  content MEDIUMTEXT NULL,
                  source_doc_id BIGINT NULL,
                  source_chunk_id BIGINT NULL,
                  meta_json JSON NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  KEY idx_cases_type (case_type),
                  CONSTRAINT fk_cases_doc FOREIGN KEY (source_doc_id) REFERENCES documents(id) ON DELETE SET NULL,
                  CONSTRAINT fk_cases_chunk FOREIGN KEY (source_chunk_id) REFERENCES chunks(id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS entities (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              entity_name VARCHAR(255) NOT NULL,
              entity_type VARCHAR(128) NULL,
              canonical_name VARCHAR(255) NULL,
              aliases JSON NULL,
              description TEXT NULL,
              meta_json JSON NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_entities_name_type (entity_name, entity_type),
              KEY idx_entities_type (entity_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        if self.table_exists("chunks"):
            self.execute(
                """
                CREATE TABLE IF NOT EXISTS document_entity_relations (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  doc_id BIGINT NOT NULL,
                  entity_id BIGINT NOT NULL,
                  chunk_id BIGINT NULL,
                  relation_type VARCHAR(128) NULL,
                  confidence_score FLOAT DEFAULT 1.0,
                  meta_json JSON NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE KEY uq_doc_entity_chunk (doc_id, entity_id, chunk_id),
                  KEY idx_der_doc (doc_id),
                  KEY idx_der_entity (entity_id),
                  CONSTRAINT fk_der_doc FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
                  CONSTRAINT fk_der_entity FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
                  CONSTRAINT fk_der_chunk FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )

    def get_or_create_document(self, *, source: str, title: str | None, sha256: str, mime: str) -> int:
        row = self.fetchone("SELECT id FROM documents WHERE sha256=%s", (sha256,))
        if row:
            return int(row[0])
        self.execute(
            """
            INSERT INTO documents
                (source,title,sha256,mime,doc_type,language,local_path,is_public,meta_json)
            VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS JSON))
            """,
            (source, title or source, sha256, mime, None, "zh-CN", source, 1, "{}"),
        )
        row = self.fetchone("SELECT id FROM documents WHERE sha256=%s", (sha256,))
        if not row:
            raise RuntimeError(f"failed to create document sha256={sha256}")
        return int(row[0])

    def count_chunks_for_doc(self, doc_id: int) -> int:
        row = self.fetchone("SELECT COUNT(*) FROM chunks WHERE doc_id=%s", (int(doc_id),))
        return int(row[0]) if row else 0

    def delete_chunks_for_doc(self, doc_id: int) -> int:
        return self.execute("DELETE FROM chunks WHERE doc_id=%s", (int(doc_id),))

    def insert_chunks(self, *, doc_id: int, rows: Sequence[ChunkInsertRow]) -> None:
        if not rows:
            return
        self.executemany(
            """
            INSERT INTO chunks
                (doc_id,chunk_index,page_start,page_end,chunk_type,section_path,text,
                 char_len,token_len,content_hash,quality_score,meta_json,is_active)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS JSON),%s)
            ON DUPLICATE KEY UPDATE
                page_start=VALUES(page_start),
                page_end=VALUES(page_end),
                chunk_type=VALUES(chunk_type),
                section_path=VALUES(section_path),
                text=VALUES(text),
                char_len=VALUES(char_len),
                token_len=VALUES(token_len),
                content_hash=VALUES(content_hash),
                quality_score=VALUES(quality_score),
                meta_json=VALUES(meta_json),
                is_active=VALUES(is_active),
                updated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    doc_id,
                    row.chunk_index,
                    row.page_start,
                    row.page_end,
                    row.chunk_type or "text",
                    row.section_path,
                    row.text,
                    row.char_len,
                    row.token_len,
                    row.content_hash,
                    row.quality_score,
                    row.meta_json_text() or "{}",
                    row.is_active,
                )
                for row in rows
            ],
        )

    def list_chunks_text(self, *, doc_id: int) -> list[tuple[int, int, str]]:
        return [
            (int(a), int(b), str(c))
            for (a, b, c) in self.fetchall(
                "SELECT id,chunk_index,text FROM chunks WHERE doc_id=%s AND is_active=1 ORDER BY chunk_index",
                (doc_id,),
            )
        ]

    def list_active_chunks_for_rebuild(self) -> list[tuple[int, str, str, int | None]]:
        rows = self.fetchall(
            "SELECT id, text, chunk_type, token_len FROM chunks WHERE is_active=1 AND text IS NOT NULL AND CHAR_LENGTH(text) > 0 ORDER BY id ASC"
        )
        return [(int(cid), str(txt), str(ctype or "text"), int(tlen) if tlen is not None else None) for (cid, txt, ctype, tlen) in rows]

    def list_active_chunks_for_bm25(self) -> list[tuple[int, str, str]]:
        rows = self.fetchall(
            "SELECT id, text, chunk_type FROM chunks WHERE is_active=1 AND text IS NOT NULL AND CHAR_LENGTH(text) > 0 ORDER BY id ASC"
        )
        return [(int(cid), str(txt), str(ctype or "text")) for (cid, txt, ctype) in rows]

    @staticmethod
    def _to_chunk_record(row: tuple | None) -> ChunkRecord | None:
        if not row:
            return None
        return ChunkRecord(
            id=int(row[0]),
            doc_id=int(row[1]),
            chunk_index=int(row[2]),
            page_start=int(row[3]) if row[3] is not None else None,
            page_end=int(row[4]) if row[4] is not None else None,
            chunk_type=str(row[5] or "text"),
            text=str(row[6] or ""),
            token_len=int(row[7]) if row[7] is not None else None,
            section_path=str(row[8]) if row[8] is not None else None,
            content_hash=str(row[9]) if row[9] is not None else None,
            meta_json=str(row[10]) if row[10] is not None else None,
        )

    def _chunk_select_sql(self) -> str:
        return "SELECT id, doc_id, chunk_index, page_start, page_end, chunk_type, text, token_len, section_path, content_hash, meta_json FROM chunks"

    def get_chunk_record_by_id(self, chunk_id: int) -> ChunkRecord | None:
        row = self.fetchone(
            self._chunk_select_sql() + " WHERE id=%s",
            (chunk_id,),
        )
        return self._to_chunk_record(row)

    def bulk_get_chunk_records_by_ids(self, chunk_ids: Sequence[int]) -> list[ChunkRecord]:
        ids = [int(x) for x in chunk_ids if x is not None]
        if not ids:
            return []
        placeholders = ",".join(["%s"] * len(ids))
        rows = self.fetchall(
            self._chunk_select_sql() + f" WHERE id IN ({placeholders}) ORDER BY id",
            tuple(ids),
        )
        return [rec for row in rows if (rec := self._to_chunk_record(row)) is not None]

    def list_neighbor_chunk_records(self, *, doc_id: int, chunk_index: int, window: int = 1) -> list[ChunkRecord]:
        lo = int(chunk_index) - int(window)
        hi = int(chunk_index) + int(window)
        rows = self.fetchall(
            self._chunk_select_sql() + " WHERE doc_id=%s AND is_active=1 AND chunk_index BETWEEN %s AND %s ORDER BY chunk_index",
            (int(doc_id), lo, hi),
        )
        return [rec for row in rows if (rec := self._to_chunk_record(row)) is not None]

    def get_chunk_full_by_id(self, chunk_id: int) -> Optional[tuple]:
        rec = self.get_chunk_record_by_id(chunk_id)
        if rec is None:
            return None
        return (rec.id, rec.doc_id, rec.chunk_index, rec.page_start, rec.page_end, rec.chunk_type, rec.text, rec.token_len, rec.section_path, rec.content_hash, rec.meta_json)

    def bulk_get_chunks_by_ids(self, chunk_ids: Sequence[int]) -> list[tuple]:
        return [
            (rec.id, rec.doc_id, rec.chunk_index, rec.page_start, rec.page_end, rec.chunk_type, rec.text, rec.token_len, rec.section_path, rec.content_hash, rec.meta_json)
            for rec in self.bulk_get_chunk_records_by_ids(chunk_ids)
        ]

    def list_neighbor_chunks(self, *, doc_id: int, chunk_index: int, window: int = 1) -> list[tuple]:
        return [
            (rec.id, rec.doc_id, rec.chunk_index, rec.page_start, rec.page_end, rec.chunk_type, rec.text, rec.token_len, rec.section_path, rec.content_hash, rec.meta_json)
            for rec in self.list_neighbor_chunk_records(doc_id=doc_id, chunk_index=chunk_index, window=window)
        ]

    def upsert_embeddings_meta(self, *, items: Iterable[tuple[int, str, int, int]]) -> None:
        items = list(items)
        if not items:
            return
        build_id = hashlib.sha1(str(items[:1]).encode("utf-8")).hexdigest()[:16]
        self.executemany(
            """
            INSERT INTO embeddings(chunk_id,model_name,embedding_model,dim,vector_pos,index_name,index_version,build_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                model_name=VALUES(model_name),
                embedding_model=VALUES(embedding_model),
                dim=VALUES(dim),
                vector_pos=VALUES(vector_pos),
                index_name=VALUES(index_name),
                index_version=VALUES(index_version),
                build_id=VALUES(build_id)
            """,
            [
                (chunk_id, model_name, model_name, dim, vector_pos, "faiss", build_id, build_id)
                for (chunk_id, model_name, dim, vector_pos) in items
            ],
        )

    def get_chunk_basic(self, chunk_id: int) -> Optional[tuple]:
        return self.fetchone("SELECT id, doc_id, chunk_index, page_start, page_end, text FROM chunks WHERE id=%s", (chunk_id,))

    def vectorpos_to_chunk(self, vector_pos: int) -> int | None:
        row = self.fetchone("SELECT chunk_id FROM embeddings WHERE vector_pos=%s", (vector_pos,))
        return int(row[0]) if row else None

    def log_retrieval(self, *, query_text: str, topk: int, faiss_topn: int, latency_ms: int, model_name: str, hit_vector_pos: str | list[int] | None, hit_chunk_ids: str | list[int] | None) -> None:
        def _to_json_text(v: str | list[int] | None) -> str | None:
            if v is None:
                return None
            if isinstance(v, str):
                return v
            return json.dumps(v, ensure_ascii=False)

        hit_ids = hit_chunk_ids if isinstance(hit_chunk_ids, list) else None
        result_json = json.dumps({"hit_chunk_ids": hit_ids or hit_chunk_ids}, ensure_ascii=False)
        self.execute(
            """
            INSERT INTO retrieval_log
                (query_text,rewritten_query,top_k,topk,hit_count,faiss_topn,latency_ms,model_name,hit_vector_pos,hit_chunk_ids,result_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS JSON))
            """,
            (
                query_text,
                None,
                topk,
                topk,
                len(hit_ids) if hit_ids is not None else None,
                faiss_topn,
                latency_ms,
                model_name,
                _to_json_text(hit_vector_pos),
                _to_json_text(hit_chunk_ids),
                result_json,
            ),
        )
