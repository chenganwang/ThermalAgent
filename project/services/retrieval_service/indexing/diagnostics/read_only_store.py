from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import re

from services.ingest_service.external_ingestion import connect_mysql
from services.retrieval_service.config import AppConfig
from services.retrieval_service.indexing.explicit_bundles import (
    build_candidate_bundle,
    build_old_bundle,
)


_READ_ONLY_PREFIXES = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SelectOnlyChunkStore:
    """Minimal DB interface for diagnostics, with writes rejected before execute."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.connection = connect_mysql(cfg, autocommit=True)
        self.executed_statements: list[str] = []
        self.rejected_write_attempts = 0
        self._rows: dict[int, tuple] = {}
        self._catalog: dict[int, dict[str, Any]] = {}

    @staticmethod
    def _statement_type(sql: str) -> str:
        cleaned = re.sub(r"^\s*(?:/\*.*?\*/\s*)*", "", str(sql or ""), flags=re.S)
        return (cleaned.split(None, 1)[0] if cleaned.split(None, 1) else "").upper()

    def _assert_read_only(self, sql: str) -> None:
        statement_type = self._statement_type(sql)
        if statement_type not in _READ_ONLY_PREFIXES:
            self.rejected_write_attempts += 1
            raise ValueError(f"diagnostics database is SELECT-only: rejected {statement_type or 'empty'}")

    def fetchall(self, sql: str, params: tuple | None = None) -> list[tuple]:
        self._assert_read_only(sql)
        cursor = self.connection.cursor()
        cursor.execute(sql, params or ())
        self.executed_statements.append(self._statement_type(sql))
        return list(cursor.fetchall() or [])

    def fetchone(self, sql: str, params: tuple | None = None):
        self._assert_read_only(sql)
        cursor = self.connection.cursor()
        cursor.execute(sql, params or ())
        self.executed_statements.append(self._statement_type(sql))
        return cursor.fetchone()

    def table_counts(self, tables: Iterable[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in tables:
            if not _SAFE_IDENTIFIER.fullmatch(str(table)):
                raise ValueError(f"unsafe table identifier: {table}")
            row = self.fetchone(f"SELECT COUNT(*) FROM {table}")
            counts[str(table)] = int(row[0]) if row else 0
        return counts

    def load_chunk_catalog(self) -> dict[int, dict[str, Any]]:
        cursor = self.connection.cursor(dictionary=True)
        sql = """
            SELECT
                c.id AS chunk_id,
                c.doc_id AS document_id,
                c.chunk_index,
                c.page_start,
                c.page_end,
                c.chunk_type,
                c.text,
                c.token_len,
                c.section_path,
                c.content_hash,
                c.meta_json,
                d.title AS document_title,
                d.source AS document_source,
                d.local_path,
                sa.id AS source_asset_id
            FROM chunks c
            JOIN documents d ON d.id=c.doc_id
            LEFT JOIN (
                SELECT doc_id, MIN(id) AS id
                FROM source_assets
                GROUP BY doc_id
            ) first_asset ON first_asset.doc_id=d.id
            LEFT JOIN source_assets sa ON sa.id=first_asset.id
            WHERE c.is_active=1
            ORDER BY c.id
        """
        self._assert_read_only(sql)
        cursor.execute(sql)
        self.executed_statements.append("SELECT")
        catalog: dict[int, dict[str, Any]] = {}
        rows: dict[int, tuple] = {}
        for raw in cursor.fetchall() or []:
            item = dict(raw)
            chunk_id = int(item["chunk_id"])
            source_value = str(item.get("document_source") or item.get("local_path") or "")
            source_name = Path(source_value).name if source_value else str(item.get("document_title") or "")
            catalog[chunk_id] = {
                "chunk_id": chunk_id,
                "document_id": int(item["document_id"]),
                "source_asset_id": (
                    int(item["source_asset_id"]) if item.get("source_asset_id") is not None else None
                ),
                "document_title": item.get("document_title"),
                "source_name": source_name,
                "section_title": item.get("section_path"),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "chunk_type": item.get("chunk_type"),
                "chunk_index": int(item.get("chunk_index") or 0),
                "text": str(item.get("text") or ""),
                "content_hash": item.get("content_hash"),
            }
            rows[chunk_id] = (
                chunk_id,
                int(item["document_id"]),
                int(item.get("chunk_index") or 0),
                item.get("page_start"),
                item.get("page_end"),
                item.get("chunk_type"),
                item.get("text"),
                item.get("token_len"),
                item.get("section_path"),
                item.get("content_hash"),
                item.get("meta_json"),
            )
        self._catalog = catalog
        self._rows = rows
        return {key: dict(value) for key, value in catalog.items()}

    def get_chunk_full_by_id(self, chunk_id: int):
        if not self._rows:
            self.load_chunk_catalog()
        return self._rows.get(int(chunk_id))

    def list_active_chunks_for_bm25(self) -> list[tuple[int, str, str]]:
        rows = self.fetchall("SELECT id, text, chunk_type FROM chunks WHERE is_active=1 AND text IS NOT NULL AND CHAR_LENGTH(text)>0 ORDER BY id")
        return [(int(row[0]), str(row[1]), str(row[2] or "text")) for row in rows]

    def list_neighbor_chunks(self, *, doc_id: int, chunk_index: int, window: int = 1) -> list[tuple]:
        if not self._rows:
            self.load_chunk_catalog()
        low = int(chunk_index) - int(window)
        high = int(chunk_index) + int(window)
        return sorted(
            [
                row
                for row in self._rows.values()
                if int(row[1]) == int(doc_id) and low <= int(row[2]) <= high
            ],
            key=lambda row: int(row[2]),
        )

    @property
    def catalog(self) -> dict[int, dict[str, Any]]:
        if not self._catalog:
            self.load_chunk_catalog()
        return {key: dict(value) for key, value in self._catalog.items()}

    def close(self) -> None:
        self.connection.close()


def load_explicit_bundles(cfg: AppConfig, build: dict[str, Any]) -> dict[str, dict[str, Any]]:
    old = build_old_bundle(cfg)
    candidate = build_candidate_bundle(build)
    old["knowledge_units_included"] = False
    candidate["knowledge_units_included"] = False
    return {"old": old, "candidate": candidate}
