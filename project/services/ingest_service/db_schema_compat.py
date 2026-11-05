from __future__ import annotations

"""Compatibility helpers for the rag_agent MySQL schema.

The ingest service imports the project DB object from
``services.retrieval_service.db``.  Different project packages may expose a
slightly different DB implementation, so this module keeps the ingest-side
interface stable while writing rows that match ``rag_agent_schema.sql``.
"""

import json
from pathlib import Path
from typing import Any, Iterable

def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _fetchone(db: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    if hasattr(db, "fetchone"):
        return db.fetchone(sql, params)
    raise AttributeError("DB object must provide fetchone(sql, params) for schema compatibility fallback")


def _execute(db: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    if hasattr(db, "execute"):
        return db.execute(sql, params)
    raise AttributeError("DB object must provide execute(sql, params) for schema compatibility fallback")


def _executemany(db: Any, sql: str, params: Iterable[tuple[Any, ...]]) -> Any:
    items = list(params)
    if not items:
        return None
    if hasattr(db, "executemany"):
        return db.executemany(sql, items)
    for item in items:
        _execute(db, sql, item)
    return None


def table_exists(db: Any, table_name: str) -> bool:
    row = _fetchone(
        db,
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = %s
        """,
        (table_name,),
    )
    return bool(row and int(row[0]) > 0)


def column_exists(db: Any, table_name: str, column_name: str) -> bool:
    row = _fetchone(
        db,
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
        """,
        (table_name, column_name),
    )
    return bool(row and int(row[0]) > 0)


def get_or_create_document_compat(
    db: Any,
    *,
    source: str,
    title: str,
    sha256: str,
    mime: str | None,
    doc_type: str | None = None,
    organization: str | None = None,
    language: str = "zh-CN",
    publish_year: int | None = None,
    url: str | None = None,
    local_path: str | None = None,
    is_public: int = 1,
    license_note: str | None = None,
    meta_json: dict[str, Any] | None = None,
) -> int:
    """Create or fetch one row in the rag_agent.documents table.

    The public ingest functions keep calling a small helper instead of relying
    on a particular external DB implementation.  Required columns in the new
    schema are always populated; optional metadata is written when available.
    """

    local_path = local_path or (str(Path(source)) if source else None)

    sql = """
        INSERT INTO documents
            (source, title, sha256, mime, doc_type, organization, language,
             publish_year, url, local_path, is_public, license_note, meta_json)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON))
        ON DUPLICATE KEY UPDATE
            id = LAST_INSERT_ID(id),
            source = VALUES(source),
            title = VALUES(title),
            mime = VALUES(mime),
            doc_type = COALESCE(VALUES(doc_type), doc_type),
            organization = COALESCE(VALUES(organization), organization),
            language = COALESCE(VALUES(language), language),
            publish_year = COALESCE(VALUES(publish_year), publish_year),
            url = COALESCE(VALUES(url), url),
            local_path = COALESCE(VALUES(local_path), local_path),
            is_public = VALUES(is_public),
            license_note = COALESCE(VALUES(license_note), license_note),
            meta_json = COALESCE(VALUES(meta_json), meta_json),
            updated_at = CURRENT_TIMESTAMP
    """
    meta_text = _json_text(meta_json) or "{}"
    result = _execute(
        db,
        sql,
        (
            source,
            title,
            sha256,
            mime,
            doc_type,
            organization,
            language,
            publish_year,
            url,
            local_path,
            int(is_public),
            license_note,
            meta_text,
        ),
    )
    lastrowid = getattr(result, "lastrowid", None)
    if lastrowid:
        return int(lastrowid)
    row = _fetchone(db, "SELECT id FROM documents WHERE sha256=%s", (sha256,))
    if not row:
        raise RuntimeError(f"failed to create or fetch document sha256={sha256}")
    return int(row[0])


def count_chunks_for_doc_compat(db: Any, doc_id: int) -> int:
    row = _fetchone(db, "SELECT COUNT(*) FROM chunks WHERE doc_id=%s", (int(doc_id),))
    return int(row[0]) if row else 0


def delete_chunks_for_doc_compat(db: Any, doc_id: int) -> None:
    # ON DELETE CASCADE / SET NULL constraints in rag_agent_schema.sql handle
    # dependent records where applicable.
    _execute(db, "DELETE FROM chunks WHERE doc_id=%s", (int(doc_id),))


def insert_chunks_compat(db: Any, *, doc_id: int, rows: list[Any]) -> None:
    """Insert chunk rows using the authoritative rag_agent.chunks columns."""
    if not rows:
        return
    sql = """
        INSERT INTO chunks
            (doc_id, chunk_index, page_start, page_end, chunk_type, section_path,
             text, char_len, token_len, content_hash, quality_score, meta_json, is_active)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), %s)
        ON DUPLICATE KEY UPDATE
            page_start = VALUES(page_start),
            page_end = VALUES(page_end),
            chunk_type = VALUES(chunk_type),
            section_path = VALUES(section_path),
            text = VALUES(text),
            char_len = VALUES(char_len),
            token_len = VALUES(token_len),
            content_hash = VALUES(content_hash),
            quality_score = VALUES(quality_score),
            meta_json = VALUES(meta_json),
            is_active = VALUES(is_active),
            updated_at = CURRENT_TIMESTAMP
    """
    values = []
    for row in rows:
        values.append(
            (
                int(doc_id),
                int(row.chunk_index),
                row.page_start,
                row.page_end,
                row.chunk_type or "text",
                row.section_path,
                row.text,
                row.char_len,
                row.token_len,
                row.content_hash,
                row.quality_score,
                _json_text(row.meta_json) or "{}",
                int(row.is_active),
            )
        )
    _executemany(db, sql, values)


def sync_document_sections_for_doc(db: Any, *, doc_id: int) -> int:
    """Populate document_sections from chunk section_path values when present."""

    if not table_exists(db, "document_sections") or not column_exists(db, "chunks", "section_id"):
        return 0
    rows = _fetchone(db, "SELECT COUNT(*) FROM chunks WHERE doc_id=%s AND section_path IS NOT NULL AND section_path<>''", (int(doc_id),))
    if not rows or int(rows[0]) <= 0:
        return 0
    section_rows = []
    distinct_rows = getattr(db, "fetchall")(
        """
        SELECT section_path, MIN(page_start), MAX(page_end)
        FROM chunks
        WHERE doc_id=%s AND section_path IS NOT NULL AND section_path<>''
        GROUP BY section_path
        """,
        (int(doc_id),),
    )
    for section_path, page_start, page_end in distinct_rows:
        path = str(section_path or "").strip()
        if not path:
            continue
        parts = [p.strip() for p in path.replace("\\", "/").split("/") if p.strip()]
        title = parts[-1] if parts else path
        section_rows.append((int(doc_id), title, path, len(parts) or 1, page_start, page_end, "{}"))
    if not section_rows:
        return 0
    _executemany(
        db,
        """
        INSERT INTO document_sections
            (doc_id,title,section_path,level,page_start,page_end,meta_json)
        VALUES
            (%s,%s,%s,%s,%s,%s,CAST(%s AS JSON))
        ON DUPLICATE KEY UPDATE
            title=VALUES(title),
            level=VALUES(level),
            page_start=VALUES(page_start),
            page_end=VALUES(page_end),
            updated_at=CURRENT_TIMESTAMP
        """,
        section_rows,
    )
    _execute(
        db,
        """
        UPDATE chunks c
        JOIN document_sections s
          ON s.doc_id = c.doc_id AND s.section_path = c.section_path
        SET c.section_id = s.id
        WHERE c.doc_id=%s
        """,
        (int(doc_id),),
    )
    return len(section_rows)


def safe_wipe_embeddings_rows(db: Any) -> bool:
    """Truncate embeddings only when the runtime schema actually has it."""
    try:
        if not table_exists(db, "embeddings"):
            print("[warn] embeddings table not found in current MySQL schema; skip DB embedding mapping wipe")
            return False
        _execute(db, "TRUNCATE TABLE embeddings")
        return True
    except Exception as exc:
        print(f"[warn] failed to wipe embeddings table; skip DB embedding mapping wipe: {exc}")
        return False


def safe_upsert_embeddings_meta(db: Any, *, items: list[tuple[int, str, int, int]]) -> bool:
    """Write embedding metadata when the external DB layer/schema supports it."""
    if not items:
        return True
    if hasattr(db, "upsert_embeddings_meta"):
        try:
            db.upsert_embeddings_meta(items=items)
            return True
        except Exception as exc:
            print(f"[warn] db.upsert_embeddings_meta failed; trying SQL fallback: {exc}")
    try:
        if not table_exists(db, "embeddings"):
            print("[warn] embeddings table not found; FAISS vectors were written without MySQL vector_pos mapping")
            return False
        sql = """
            INSERT INTO embeddings (chunk_id, model_name, dim, vector_pos)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                model_name = VALUES(model_name),
                dim = VALUES(dim),
                vector_pos = VALUES(vector_pos)
        """
        _executemany(db, sql, items)
        return True
    except Exception as exc:
        print(f"[warn] failed to write embeddings metadata; FAISS files are still rebuilt: {exc}")
        return False
