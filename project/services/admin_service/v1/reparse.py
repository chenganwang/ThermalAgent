from __future__ import annotations

from datetime import date, datetime, time, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Protocol
from uuid import uuid4

from services.ingest_service.knowledge.quality import analyze_chunk_quality
from services.ingest_service.knowledge.corrections import KnowledgeCorrectionError, chunk_rows_digest
from services.ingest_service.knowledge.correction_repository import MySQLChunkMutationStore
from services.ingest_service.knowledge.page_reparse import CanonicalPageParser, STANDARD_PDF_TEXT_STRATEGY

from .documents import DocumentAdminRepository

from ..contracts import AdminAPIError


_PREVIEW_ID = re.compile(r"^reparse-[a-f0-9]{32}$")


class PageReparseAdapter(Protocol):
    def available_strategies(self, document_id: int) -> list[str]: ...
    def list_page_chunks(self, document_id: int, page_number: int) -> list[dict[str, Any]]: ...
    def parse_page(self, document_id: int, page_number: int, strategy: str) -> dict[str, Any]: ...
    def apply_page(self, **kwargs: Any) -> dict[str, Any]: ...


class PageReparsePreviewStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._lock = RLock()

    def save(self, value: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(value)
        preview_id = self._id(str(payload.get("preview_id") or ""))
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{preview_id}.json"
        temporary = path.with_suffix(".json.tmp")
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
        normalized = json.loads(serialized)
        with self._lock:
            temporary.write_text(serialized, encoding="utf-8")
            temporary.replace(path)
        return normalized

    def get(self, preview_id: str) -> dict[str, Any]:
        normalized = self._id(preview_id)
        path = self.root / f"{normalized}.json"
        if not path.is_file():
            raise AdminAPIError("PAGE_REPARSE_PREVIEW_NOT_FOUND", "Page reparse preview was not found.", status_code=404)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise AdminAPIError("PAGE_REPARSE_PREVIEW_CORRUPT", "Page reparse preview is unreadable.", status_code=500) from exc
        if not isinstance(value, dict):
            raise AdminAPIError("PAGE_REPARSE_PREVIEW_CORRUPT", "Page reparse preview is invalid.", status_code=500)
        return value

    @staticmethod
    def _id(value: str) -> str:
        if not _PREVIEW_ID.fullmatch(str(value or "")):
            raise AdminAPIError("PAGE_REPARSE_PREVIEW_ID_INVALID", "Invalid page reparse preview identifier.", status_code=422)
        return value


class PageReparseAdminService:
    def __init__(self, store: PageReparsePreviewStore, adapter: PageReparseAdapter) -> None:
        self.store = store
        self.adapter = adapter
        self._lock = RLock()

    def create_preview(
        self,
        *,
        document_id: int,
        page_number: int,
        strategy: str,
        actor_id: str,
    ) -> dict[str, Any]:
        doc_id = _positive(document_id, "DOCUMENT")
        page = _positive(page_number, "PAGE")
        normalized_strategy = str(strategy or "").strip()
        strategies = self.adapter.available_strategies(doc_id)
        if normalized_strategy not in strategies:
            raise AdminAPIError(
                "PAGE_REPARSE_STRATEGY_UNSUPPORTED",
                "The selected parser strategy is not available for this document.",
                status_code=422,
                details={"available_strategies": strategies},
            )
        try:
            current = [dict(row) for row in self.adapter.list_page_chunks(doc_id, page)]
            parsed = self.adapter.parse_page(doc_id, page, normalized_strategy)
        except AdminAPIError:
            raise
        except Exception as exc:
            raise AdminAPIError(
                "PAGE_REPARSE_FAILED",
                "Page reparse failed; existing content was not changed.",
                status_code=422,
                details={"error_type": type(exc).__name__},
            ) from exc
        candidate = [_candidate_row(row, page) for row in parsed.get("rows") or []]
        if not candidate:
            raise AdminAPIError("PAGE_REPARSE_EMPTY", "Page reparse produced no usable content.", status_code=422)
        preview_id = f"reparse-{uuid4().hex}"
        old_digest = chunk_rows_digest(current)
        new_digest = chunk_rows_digest(candidate)
        payload = {
            "preview_id": preview_id,
            "status": "preview_ready",
            "document_id": doc_id,
            "page_number": page,
            "strategy": normalized_strategy,
            "parser": parsed.get("parser"),
            "parser_version": parsed.get("parser_version"),
            "old_chunk_count": len(current),
            "new_chunk_count": len(candidate),
            "old_chunks": current,
            "candidate_chunks": candidate,
            "base_content_digest": old_digest,
            "candidate_content_digest": new_digest,
            "diff": {
                "changed": old_digest != new_digest,
                "old_characters": sum(len(str(row.get("text") or "")) for row in current),
                "new_characters": sum(len(str(row.get("text") or "")) for row in candidate),
            },
            "quality_before": _quality_counts(current),
            "quality_after": _quality_counts(candidate),
            "warnings": [str(item)[:300] for item in parsed.get("warnings") or []],
            "canonical_modified": False,
            "index_modified": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": str(actor_id or "admin")[:200],
            "applied": False,
        }
        payload = self.store.save(payload)
        return _public_preview(payload)

    def capabilities(self, document_id: int) -> dict[str, Any]:
        doc_id = _positive(document_id, "DOCUMENT")
        strategies = self.adapter.available_strategies(doc_id)
        return {"available": bool(strategies), "strategies": strategies}

    def get_preview(self, preview_id: str) -> dict[str, Any]:
        return _public_preview(self.store.get(preview_id))

    def apply_preview(self, preview_id: str, *, actor_id: str, idempotency_key: str) -> dict[str, Any]:
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 200:
            raise AdminAPIError("IDEMPOTENCY_KEY_INVALID", "A valid idempotency key is required.", status_code=422)
        with self._lock:
            payload = self.store.get(preview_id)
            if payload.get("applied"):
                if payload.get("apply_idempotency_key") != key:
                    raise AdminAPIError("PAGE_REPARSE_ALREADY_APPLIED", "Page reparse preview was already applied.", status_code=409)
                return _public_preview(payload)
            try:
                result = self.adapter.apply_page(
                    document_id=int(payload["document_id"]),
                    page_number=int(payload["page_number"]),
                    strategy=str(payload["strategy"]),
                    preview_id=str(payload["preview_id"]),
                    base_content_digest=str(payload["base_content_digest"]),
                    candidate_chunks=[dict(row) for row in payload.get("candidate_chunks") or []],
                    actor_id=str(actor_id or "admin")[:200],
                    idempotency_key=key,
                    parser=payload.get("parser"),
                    parser_version=payload.get("parser_version"),
                )
            except AdminAPIError:
                raise
            except Exception as exc:
                raise AdminAPIError(
                    "PAGE_REPARSE_APPLY_FAILED",
                    "Page reparse could not be applied; existing content was not changed.",
                    status_code=500,
                    details={"error_type": type(exc).__name__},
                ) from exc
            payload.update({
                "status": "applied",
                "applied": True,
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "applied_by": str(actor_id or "admin")[:200],
                "apply_idempotency_key": key,
                "apply_result": dict(result),
                "canonical_modified": bool(result.get("applied")),
                "index_modified": False,
            })
            payload = self.store.save(payload)
            return _public_preview(payload)


class CanonicalPageReparseAdapter:
    def __init__(
        self,
        documents: DocumentAdminRepository,
        chunks: MySQLChunkMutationStore,
        parser: CanonicalPageParser,
    ) -> None:
        self.documents = documents
        self.chunks = chunks
        self.parser = parser

    def available_strategies(self, document_id: int) -> list[str]:
        try:
            resource = self.documents.resolve_content(document_id)
        except AdminAPIError:
            return []
        return [STANDARD_PDF_TEXT_STRATEGY] if resource.path.suffix.lower() == ".pdf" else []

    def list_page_chunks(self, document_id: int, page_number: int) -> list[dict[str, Any]]:
        return self.chunks.list_page_chunks(document_id, page_number)

    def parse_page(self, document_id: int, page_number: int, strategy: str) -> dict[str, Any]:
        resource = self.documents.resolve_content(document_id)
        try:
            return self.parser.parse(resource.path, page_number=page_number, strategy=strategy)
        except KnowledgeCorrectionError as exc:
            raise AdminAPIError(exc.code, exc.message, status_code=exc.status_code) from exc

    def apply_page(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return self.chunks.apply_page_reparse(**kwargs)
        except KnowledgeCorrectionError as exc:
            raise AdminAPIError(exc.code, exc.message, status_code=exc.status_code) from exc


def _candidate_row(row: Any, page_number: int) -> dict[str, Any]:
    if isinstance(row, Mapping):
        raw = dict(row)
    else:
        raw = {name: getattr(row, name, None) for name in (
            "chunk_index", "page_start", "page_end", "chunk_type", "section_path", "text", "meta_json",
        )}
    text = str(raw.get("text") or "")
    return {
        "chunk_index": int(raw.get("chunk_index") or 0),
        "page_start": int(raw.get("page_start") or page_number),
        "page_end": int(raw.get("page_end") or page_number),
        "chunk_type": str(raw.get("chunk_type") or "text"),
        "section_path": raw.get("section_path"),
        "text": text,
        "content_hash": sha256(text.encode("utf-8")).hexdigest(),
        "meta_json": dict(raw.get("meta_json")) if isinstance(raw.get("meta_json"), Mapping) else {},
        "quality": analyze_chunk_quality(text, chunk_type=str(raw.get("chunk_type") or "text")),
    }


def _quality_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"normal": 0, "needs_review": 0, "suspected_parse_error": 0}
    for row in rows:
        quality = row.get("quality")
        if not isinstance(quality, Mapping):
            quality = analyze_chunk_quality(str(row.get("text") or ""), chunk_type=str(row.get("chunk_type") or "text"))
        state = str(quality.get("state") or "needs_review")
        counts[state if state in counts else "needs_review"] += 1
    return counts


def _public_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "preview_id", "status", "document_id", "page_number", "strategy", "parser", "parser_version",
        "old_chunk_count", "new_chunk_count", "old_chunks", "candidate_chunks", "diff", "quality_before",
        "quality_after", "warnings", "canonical_modified", "index_modified", "created_at", "applied",
        "applied_at", "apply_result",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _positive(value: int, prefix: str) -> int:
    normalized = int(value)
    if normalized <= 0:
        raise AdminAPIError(f"{prefix}_ID_INVALID", f"Invalid {prefix.lower()} identifier.", status_code=422)
    return normalized


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


__all__ = ["CanonicalPageReparseAdapter", "PageReparseAdapter", "PageReparseAdminService", "PageReparsePreviewStore"]
