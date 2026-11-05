from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Callable
from uuid import uuid4

from services.ingest_service.external_ingestion import connect_mysql
from services.retrieval_service.config import AppConfig

from .corrections import KnowledgeCorrectionError, chunk_rows_digest


_CHUNK_SELECT = """
SELECT id AS chunk_id, doc_id AS document_id, chunk_index, page_start, page_end,
       chunk_type, section_path, text, char_len, token_len, content_hash,
       quality_score, meta_json, is_active, created_at, updated_at
FROM chunks WHERE id=%s AND doc_id=%s LIMIT 1
"""


class MySQLChunkMutationStore:
    """Transactional canonical chunk store used by Knowledge Correction."""

    def __init__(
        self,
        cfg: AppConfig,
        *,
        connection_factory: Callable[..., Any] = connect_mysql,
    ) -> None:
        self.cfg = cfg
        self.connection_factory = connection_factory

    def read_chunk(self, document_id: int, chunk_id: int) -> dict[str, Any] | None:
        connection = self.connection_factory(self.cfg, autocommit=True)
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(_CHUNK_SELECT, (int(chunk_id), int(document_id)))
            row = cursor.fetchone()
            return deepcopy(dict(row)) if row else None
        finally:
            connection.close()

    def mutate_chunk(
        self,
        document_id: int,
        chunk_id: int,
        mutation: Callable[[dict[str, Any] | None], tuple[dict[str, Any] | None, dict[str, Any]]],
    ) -> dict[str, Any]:
        connection = self.connection_factory(self.cfg, autocommit=False)
        try:
            if hasattr(connection, "start_transaction"):
                connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(_CHUNK_SELECT.rstrip() + " FOR UPDATE", (int(chunk_id), int(document_id)))
            row = cursor.fetchone()
            updated, result = mutation(deepcopy(dict(row)) if row else None)
            if updated is None:
                connection.rollback()
                return deepcopy(result)
            metadata = updated.get("meta_json")
            metadata_text = json.dumps(metadata if isinstance(metadata, dict) else {}, ensure_ascii=False)
            cursor.execute(
                """
                UPDATE chunks
                SET text=%s, char_len=%s, content_hash=%s, meta_json=CAST(%s AS JSON), updated_at=CURRENT_TIMESTAMP
                WHERE id=%s AND doc_id=%s
                """,
                (
                    str(updated.get("text") or ""),
                    int(updated.get("char_len") or 0),
                    str(updated.get("content_hash") or ""),
                    metadata_text,
                    int(chunk_id),
                    int(document_id),
                ),
            )
            connection.commit()
            return deepcopy(result)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_page_chunks(self, document_id: int, page_number: int) -> list[dict[str, Any]]:
        connection = self.connection_factory(self.cfg, autocommit=True)
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                _CHUNK_SELECT.replace("WHERE id=%s AND doc_id=%s LIMIT 1", "")
                + " WHERE doc_id=%s AND is_active=1 AND "
                "(page_start=%s OR page_end=%s OR (page_start<=%s AND page_end>=%s)) ORDER BY chunk_index",
                (int(document_id), int(page_number), int(page_number), int(page_number), int(page_number)),
            )
            return [deepcopy(dict(row)) for row in cursor.fetchall() or []]
        finally:
            connection.close()

    def apply_page_reparse(
        self,
        *,
        document_id: int,
        page_number: int,
        candidate_chunks: list[dict[str, Any]],
        base_content_digest: str,
        actor_id: str,
        idempotency_key: str,
        preview_id: str,
        parser: str | None,
        parser_version: str | None,
    ) -> dict[str, Any]:
        doc_id = int(document_id)
        page = int(page_number)
        candidates = [dict(item) for item in candidate_chunks]
        if not candidates or any(int(item.get("page_start") or page) != page or int(item.get("page_end") or page) != page for item in candidates):
            raise KnowledgeCorrectionError("PAGE_REPARSE_SCOPE_INVALID", "Reparse candidates must belong to the selected page.", status_code=422)
        connection = self.connection_factory(self.cfg, autocommit=False)
        try:
            if hasattr(connection, "start_transaction"):
                connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                _CHUNK_SELECT.replace("WHERE id=%s AND doc_id=%s LIMIT 1", "")
                + " WHERE doc_id=%s AND is_active=1 AND "
                "(page_start=%s OR page_end=%s OR (page_start<=%s AND page_end>=%s)) ORDER BY chunk_index FOR UPDATE",
                (doc_id, page, page, page, page),
            )
            current = [dict(row) for row in cursor.fetchall() or []]
            if any(
                int(row.get("page_start") or page) != page
                or int(row.get("page_end") or page) != page
                for row in current
            ):
                raise KnowledgeCorrectionError(
                    "PAGE_REPARSE_CROSS_PAGE_CHUNK_UNSUPPORTED",
                    "A canonical chunk spans the selected page boundary; page-only replacement was not applied.",
                    status_code=409,
                )
            for row in current:
                envelope = _correction_envelope(row)
                if any(
                    revision.get("idempotency_key") == idempotency_key
                    and revision.get("reparse_preview_id") == preview_id
                    for revision in envelope.get("revisions") or []
                    if isinstance(revision, dict)
                ):
                    connection.rollback()
                    return {
                        "applied": True,
                        "idempotent": True,
                        "document_id": doc_id,
                        "page_number": page,
                        "affected_chunk_count": len(current),
                        "index_status": "stale",
                    }
            if chunk_rows_digest(current) != str(base_content_digest):
                raise KnowledgeCorrectionError(
                    "PAGE_REPARSE_CONFLICT",
                    "Page content changed after the preview was created.",
                    status_code=409,
                )
            now = datetime.now(timezone.utc).isoformat()
            revision_ids: list[str] = []
            reused = min(len(current), len(candidates))
            for position, row in enumerate(current):
                candidate = candidates[position] if position < len(candidates) else None
                new_text = str(candidate.get("text") or "") if candidate else ""
                revision_id, metadata = _page_revision_metadata(
                    row,
                    new_text=new_text,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    preview_id=preview_id,
                    parser=parser,
                    parser_version=parser_version,
                    page_number=page,
                    now=now,
                    source="page_reparse" if candidate else "page_reparse_deactivate",
                )
                revision_ids.append(revision_id)
                content_hash = sha256(new_text.encode("utf-8")).hexdigest()
                cursor.execute(
                    """
                    UPDATE chunks SET page_start=%s, page_end=%s, chunk_type=%s, section_path=%s,
                        text=%s, char_len=%s, token_len=%s, content_hash=%s, quality_score=%s,
                        meta_json=CAST(%s AS JSON), is_active=%s, updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s AND doc_id=%s
                    """,
                    (
                        page,
                        page,
                        str((candidate or row).get("chunk_type") or "text"),
                        (candidate or row).get("section_path"),
                        new_text,
                        len(new_text),
                        (candidate or row).get("token_len"),
                        content_hash,
                        (candidate or row).get("quality_score"),
                        json.dumps(metadata, ensure_ascii=False),
                        1 if candidate else 0,
                        int(row["chunk_id"]),
                        doc_id,
                    ),
                )
            inserted = 0
            if len(candidates) > reused:
                cursor.execute("SELECT COALESCE(MAX(chunk_index), -1) AS n FROM chunks WHERE doc_id=%s FOR UPDATE", (doc_id,))
                maximum_value = (cursor.fetchone() or {}).get("n")
                maximum = -1 if maximum_value is None else int(maximum_value)
                for offset, candidate in enumerate(candidates[reused:], 1):
                    new_text = str(candidate.get("text") or "")
                    base_metadata = dict(candidate.get("meta_json") or {})
                    cursor.execute(
                        """
                        INSERT INTO chunks
                            (doc_id, chunk_index, page_start, page_end, chunk_type, section_path, text,
                             char_len, token_len, content_hash, quality_score, meta_json, is_active)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS JSON),1)
                        """,
                        (
                            doc_id,
                            maximum + offset,
                            page,
                            page,
                            str(candidate.get("chunk_type") or "text"),
                            candidate.get("section_path"),
                            new_text,
                            len(new_text),
                            candidate.get("token_len"),
                            sha256(new_text.encode("utf-8")).hexdigest(),
                            candidate.get("quality_score"),
                            json.dumps(base_metadata, ensure_ascii=False),
                        ),
                    )
                    inserted_chunk_id = int(getattr(cursor, "lastrowid", 0) or 0)
                    if inserted_chunk_id <= 0:
                        raise KnowledgeCorrectionError(
                            "PAGE_REPARSE_INSERT_ID_UNAVAILABLE",
                            "The inserted chunk identifier could not be verified.",
                            status_code=500,
                        )
                    row = {
                        "document_id": doc_id,
                        "chunk_id": inserted_chunk_id,
                        "chunk_index": maximum + offset,
                        "page_start": page,
                        "page_end": page,
                        "text": "",
                        "meta_json": base_metadata,
                    }
                    revision_id, metadata = _page_revision_metadata(
                        row,
                        new_text=new_text,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        preview_id=preview_id,
                        parser=parser,
                        parser_version=parser_version,
                        page_number=page,
                        now=now,
                        source="page_reparse_insert",
                    )
                    revision_ids.append(revision_id)
                    cursor.execute(
                        "UPDATE chunks SET meta_json=CAST(%s AS JSON) WHERE id=%s AND doc_id=%s",
                        (json.dumps(metadata, ensure_ascii=False), inserted_chunk_id, doc_id),
                    )
                    inserted += 1
            connection.commit()
            return {
                "applied": True,
                "idempotent": False,
                "document_id": doc_id,
                "page_number": page,
                "old_chunk_count": len(current),
                "new_chunk_count": len(candidates),
                "updated_chunk_count": reused,
                "deactivated_chunk_count": max(0, len(current) - len(candidates)),
                "inserted_chunk_count": inserted,
                "affected_chunk_count": max(len(current), len(candidates)),
                "revision_ids": revision_ids,
                "index_status": "stale",
                "active_index_modified": False,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return deepcopy(parsed) if isinstance(parsed, dict) else {}
    return {}


def _correction_envelope(row: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(row.get("meta_json"))
    value = metadata.get("knowledge_correction")
    if isinstance(value, dict):
        return deepcopy(value)
    text = str(row.get("text") or "")
    return {
        "raw_text": text,
        "raw_text_hash": sha256(text.encode("utf-8")).hexdigest(),
        "version": 0,
        "revisions": [],
        "index_status": "synced",
    }


def _page_revision_metadata(
    row: dict[str, Any],
    *,
    new_text: str,
    actor_id: str,
    idempotency_key: str,
    preview_id: str,
    parser: str | None,
    parser_version: str | None,
    page_number: int,
    now: str,
    source: str,
) -> tuple[str, dict[str, Any]]:
    metadata = _metadata(row.get("meta_json"))
    envelope = _correction_envelope(row)
    before_text = str(row.get("text") or "")
    version = int(envelope.get("version") or 0) + 1
    revision_id = f"chunk-rev-{uuid4().hex}"
    revisions = [dict(item) for item in envelope.get("revisions") or [] if isinstance(item, dict)]
    revisions.append({
        "revision_id": revision_id,
        "document_id": int(row.get("document_id") or 0),
        "chunk_id": int(row.get("chunk_id") or 0),
        "base_version": version - 1,
        "version": version,
        "before_hash": sha256(before_text.encode("utf-8")).hexdigest(),
        "after_hash": sha256(new_text.encode("utf-8")).hexdigest(),
        "before_text": before_text,
        "after_text": new_text,
        "editor": str(actor_id or "admin")[:200],
        "reason": "应用单页重新解析结果",
        "edited_at": now,
        "idempotency_key": str(idempotency_key)[:200],
        "source": source,
        "reparse_preview_id": str(preview_id)[:120],
        "page_number": int(page_number),
        "parser": parser,
        "parser_version": parser_version,
    })
    envelope.update({
        "raw_text": str(envelope.get("raw_text") if envelope.get("raw_text") is not None else before_text),
        "raw_text_hash": str(envelope.get("raw_text_hash") or sha256(before_text.encode("utf-8")).hexdigest()),
        "version": version,
        "content_revision_id": revision_id,
        "content_digest": sha256(new_text.encode("utf-8")).hexdigest(),
        "index_status": "stale",
        "revisions": revisions,
    })
    metadata["knowledge_correction"] = envelope
    metadata["page_reparse"] = {
        "preview_id": str(preview_id)[:120],
        "page_number": int(page_number),
        "parser": parser,
        "parser_version": parser_version,
        "applied_at": now,
        "confirmed_by": str(actor_id or "admin")[:200],
    }
    return revision_id, metadata


__all__ = ["MySQLChunkMutationStore"]
