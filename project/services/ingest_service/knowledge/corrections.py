from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from .quality import analyze_chunk_quality


class KnowledgeCorrectionError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = int(status_code)


class ChunkMutationStore(Protocol):
    def read_chunk(self, document_id: int, chunk_id: int) -> dict[str, Any] | None: ...

    def mutate_chunk(
        self,
        document_id: int,
        chunk_id: int,
        mutation: Callable[[dict[str, Any] | None], tuple[dict[str, Any] | None, dict[str, Any]]],
    ) -> dict[str, Any]: ...


class KnowledgeChunkCorrectionService:
    """Pure revision rules over a transactional canonical chunk store."""

    def __init__(self, store: ChunkMutationStore) -> None:
        self.store = store

    def get_chunk(self, document_id: int, chunk_id: int) -> dict[str, Any]:
        row = self.store.read_chunk(_positive_id(document_id, "document"), _positive_id(chunk_id, "chunk"))
        if row is None:
            raise KnowledgeCorrectionError("DOCUMENT_CHUNK_NOT_FOUND", "Document chunk was not found.", status_code=404)
        return _public_chunk(row)

    def revise_chunk(
        self,
        document_id: int,
        chunk_id: int,
        *,
        effective_text: str,
        reason: str,
        actor_id: str,
        base_version: int,
        idempotency_key: str,
        source: str = "manual_chunk_edit",
        restored_revision_id: str | None = None,
    ) -> dict[str, Any]:
        doc_id = _positive_id(document_id, "document")
        cid = _positive_id(chunk_id, "chunk")
        text = _effective_text(effective_text)
        key = _idempotency_key(idempotency_key)

        def mutation(row: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
            if row is None:
                raise KnowledgeCorrectionError("DOCUMENT_CHUNK_NOT_FOUND", "Document chunk was not found.", status_code=404)
            current = deepcopy(row)
            metadata = _metadata(current.get("meta_json"))
            envelope = _envelope(current, metadata)
            current_version = int(envelope.get("version") or 0)
            revisions = [dict(item) for item in envelope.get("revisions") or [] if isinstance(item, Mapping)]
            after_hash = _text_hash(text)
            prior = next((item for item in revisions if item.get("idempotency_key") == key), None)
            if prior:
                if str(prior.get("after_hash") or "") != after_hash:
                    raise KnowledgeCorrectionError("IDEMPOTENCY_CONFLICT", "The idempotency key was already used for another revision.", status_code=409)
                return None, _public_chunk(current)
            if int(base_version) != current_version:
                raise KnowledgeCorrectionError("CHUNK_REVISION_CONFLICT", "The chunk changed after it was opened.", status_code=409)
            before_text = str(current.get("text") or "")
            if text == before_text:
                return None, _public_chunk(current)
            now = datetime.now(timezone.utc).isoformat()
            revision_id = f"chunk-rev-{uuid4().hex}"
            revision = {
                "revision_id": revision_id,
                "document_id": doc_id,
                "chunk_id": cid,
                "base_version": current_version,
                "version": current_version + 1,
                "before_hash": _text_hash(before_text),
                "after_hash": after_hash,
                "before_text": before_text,
                "after_text": text,
                "editor": str(actor_id or "admin")[:200],
                "reason": str(reason or "").strip()[:500],
                "edited_at": now,
                "idempotency_key": key,
                "source": str(source or "manual_chunk_edit")[:80],
            }
            if restored_revision_id:
                revision["restored_revision_id"] = str(restored_revision_id)[:120]
            revisions.append(revision)
            envelope.update({
                "raw_text": str(envelope.get("raw_text") if envelope.get("raw_text") is not None else before_text),
                "raw_text_hash": str(envelope.get("raw_text_hash") or _text_hash(before_text)),
                "version": current_version + 1,
                "content_revision_id": revision_id,
                "content_digest": after_hash,
                "index_status": "stale",
                "revisions": revisions,
            })
            metadata["knowledge_correction"] = envelope
            current.update({
                "text": text,
                "char_len": len(text),
                "content_hash": after_hash,
                "meta_json": metadata,
            })
            return current, _public_chunk(current)

        return self.store.mutate_chunk(doc_id, cid, mutation)

    def restore_revision(
        self,
        document_id: int,
        chunk_id: int,
        *,
        revision_id: str,
        reason: str,
        actor_id: str,
        base_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        current = self.get_chunk(document_id, chunk_id)
        target_id = str(revision_id or "").strip()
        target = next((item for item in current["revisions"] if item.get("revision_id") == target_id), None)
        if target is None:
            raise KnowledgeCorrectionError("CHUNK_REVISION_NOT_FOUND", "Chunk revision was not found.", status_code=404)
        return self.revise_chunk(
            document_id,
            chunk_id,
            effective_text=str(target.get("after_text") or ""),
            reason=reason,
            actor_id=actor_id,
            base_version=base_version,
            idempotency_key=idempotency_key,
            source="restore_revision",
            restored_revision_id=target_id,
        )

    def restore_original(
        self,
        document_id: int,
        chunk_id: int,
        *,
        reason: str,
        actor_id: str,
        base_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        current = self.get_chunk(document_id, chunk_id)
        return self.revise_chunk(
            document_id,
            chunk_id,
            effective_text=str(current.get("raw_text") or ""),
            reason=reason,
            actor_id=actor_id,
            base_version=base_version,
            idempotency_key=idempotency_key,
            source="restore_parser_output",
        )


def _public_chunk(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _metadata(row.get("meta_json"))
    envelope = _envelope(row, metadata)
    text = str(row.get("text") or "")
    raw_text = str(envelope.get("raw_text") if envelope.get("raw_text") is not None else text)
    return {
        "document_id": int(row.get("document_id") or row.get("doc_id") or 0),
        "chunk_id": int(row.get("chunk_id") or row.get("id") or 0),
        "chunk_index": int(row.get("chunk_index") or 0),
        "page_start": row.get("page_start"),
        "page_end": row.get("page_end"),
        "section": row.get("section_path"),
        "raw_text": raw_text,
        "effective_text": text,
        "version": int(envelope.get("version") or 0),
        "content_revision_id": envelope.get("content_revision_id"),
        "index_status": str(envelope.get("index_status") or "synced"),
        "quality": analyze_chunk_quality(text, chunk_type=str(row.get("chunk_type") or "text")),
        "revisions": [dict(item) for item in envelope.get("revisions") or [] if isinstance(item, Mapping)],
    }


def _envelope(row: Mapping[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    value = metadata.get("knowledge_correction")
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    text = str(row.get("text") or "")
    return {
        "raw_text": text,
        "raw_text_hash": _text_hash(text),
        "version": 0,
        "content_revision_id": None,
        "content_digest": str(row.get("content_hash") or _text_hash(text)),
        "index_status": "synced",
        "revisions": [],
    }


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return deepcopy(dict(parsed)) if isinstance(parsed, Mapping) else {}
    return {}


def _effective_text(value: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise KnowledgeCorrectionError("CHUNK_TEXT_EMPTY", "Chunk text must not be empty.", status_code=422)
    if len(text) > 1_000_000:
        raise KnowledgeCorrectionError("CHUNK_TEXT_TOO_LARGE", "Chunk text exceeds the correction limit.", status_code=422)
    return text


def _idempotency_key(value: str) -> str:
    key = str(value or "").strip()
    if not key or len(key) > 200:
        raise KnowledgeCorrectionError("IDEMPOTENCY_KEY_INVALID", "A valid idempotency key is required.", status_code=422)
    return key


def _positive_id(value: int, label: str) -> int:
    normalized = int(value)
    if normalized <= 0:
        raise KnowledgeCorrectionError(f"{label.upper()}_ID_INVALID", f"Invalid {label} identifier.", status_code=422)
    return normalized


def _text_hash(text: str) -> str:
    return sha256(str(text).encode("utf-8")).hexdigest()


def chunk_rows_digest(rows: list[dict[str, Any]]) -> str:
    values = [
        {
            "chunk_id": row.get("chunk_id") or row.get("id"),
            "chunk_index": row.get("chunk_index"),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "text_hash": _text_hash(str(row.get("text") or "")),
        }
        for row in rows
    ]
    return sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = ["ChunkMutationStore", "KnowledgeChunkCorrectionService", "KnowledgeCorrectionError", "chunk_rows_digest"]
