from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from threading import RLock
from typing import Any, Mapping, Protocol
from uuid import uuid4

from services.ingest_service.chunking.rows import ChunkInsertRow
from services.ingest_service.external_ingestion import (
    connect_mysql,
    readback_external_ingestion,
    write_selected_documents,
)
from services.ingest_service.external_sources import parse_external_source
from services.ingest_service.knowledge.quality import analyze_chunk_quality
from services.retrieval_service.config import load_config

from ..checkers import utc_now_iso
from ..contracts import AdminAPIError


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx"})
DOCUMENT_MIME_TYPES = {
    ".pdf": frozenset({"application/pdf", "application/octet-stream", ""}),
    ".docx": frozenset({
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
        "",
    }),
}
_SAFE_STAGING_ID = re.compile(r"^docstage-[a-f0-9]{32}$")
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class KnowledgeAdapter(Protocol):
    def document_by_sha256(self, digest: str) -> dict[str, Any] | None: ...
    def parse(self, path: Path, *, run_id: str) -> dict[str, Any]: ...
    def commit(self, item: dict[str, Any], parsed: dict[str, Any], *, run_id: str) -> dict[str, Any]: ...
    def readback(self, item: dict[str, Any], *, expected_chunks: int) -> dict[str, Any]: ...


class KnowledgeStagingStore:
    """Opaque, host-local staging with atomic metadata writes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.files_dir = self.root / "files"
        self.metadata_dir = self.root / "metadata"
        self.chunks_dir = self.root / "chunks"
        self.withdrawn_dir = self.root / "withdrawn"
        self._lock = RLock()

    def new_id(self) -> str:
        return f"docstage-{uuid4().hex}"

    def store_file(self, staging_id: str, extension: str, content: bytes) -> Path:
        self._validate_id(staging_id)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        target = self._safe_child(self.files_dir, f"{staging_id}{extension}")
        temporary = self._safe_child(self.files_dir, f".{staging_id}.uploading")
        with self._lock:
            try:
                temporary.write_bytes(content)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    def file_path(self, record: Mapping[str, Any]) -> Path:
        staging_id = self._validate_id(str(record.get("staging_id") or ""))
        extension = str(record.get("extension") or "")
        if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
            raise AdminAPIError("DOCUMENT_TYPE_UNSUPPORTED", "Unsupported staged document type.", status_code=422)
        path = self._safe_child(self.files_dir, f"{staging_id}{extension}")
        if not path.is_file():
            raise AdminAPIError("DOCUMENT_BINARY_MISSING", "Staged document binary is missing.", status_code=404)
        return path

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(record)
        staging_id = self._validate_id(str(item.get("staging_id") or ""))
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self._safe_child(self.metadata_dir, f"{staging_id}.json")
        self._atomic_json(path, item)
        return dict(item)

    def get(self, staging_id: str) -> dict[str, Any]:
        normalized = self._validate_id(staging_id)
        path = self._safe_child(self.metadata_dir, f"{normalized}.json")
        if not path.is_file():
            raise AdminAPIError("DOCUMENT_STAGING_NOT_FOUND", "Staged document was not found.", status_code=404)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise AdminAPIError("DOCUMENT_STAGING_CORRUPT", "Staged metadata is unreadable.", status_code=500) from exc
        if not isinstance(value, dict):
            raise AdminAPIError("DOCUMENT_STAGING_CORRUPT", "Staged metadata is invalid.", status_code=500)
        return value

    def list(self) -> list[dict[str, Any]]:
        if not self.metadata_dir.is_dir():
            return []
        values: list[dict[str, Any]] = []
        for path in self.metadata_dir.glob("docstage-*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                values.append(item)
        return sorted(values, key=lambda item: str(item.get("uploaded_at") or ""), reverse=True)

    def save_chunks(self, staging_id: str, chunks: list[dict[str, Any]]) -> None:
        normalized = self._validate_id(staging_id)
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_json(self._safe_child(self.chunks_dir, f"{normalized}.json"), chunks)

    def load_chunks(self, staging_id: str) -> list[dict[str, Any]]:
        normalized = self._validate_id(staging_id)
        path = self._safe_child(self.chunks_dir, f"{normalized}.json")
        if not path.is_file():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise AdminAPIError("DOCUMENT_CHUNKS_CORRUPT", "Staged chunk data is unreadable.", status_code=500) from exc
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def get_withdrawal(self, staging_id: str) -> dict[str, Any] | None:
        normalized = self._validate_id(staging_id)
        path = self._safe_child(self.withdrawn_dir, f"{normalized}.json")
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise AdminAPIError("DOCUMENT_STAGING_CORRUPT", "Withdrawal receipt is unreadable.", status_code=500) from exc
        if not isinstance(value, dict):
            raise AdminAPIError("DOCUMENT_STAGING_CORRUPT", "Withdrawal receipt is invalid.", status_code=500)
        return value

    def withdraw(
        self,
        record: Mapping[str, Any],
        *,
        actor_id: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        staging_id = self._validate_id(str(record.get("staging_id") or ""))
        extension = str(record.get("extension") or "")
        if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
            raise AdminAPIError("DOCUMENT_TYPE_UNSUPPORTED", "Unsupported staged document type.", status_code=422)
        self.withdrawn_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            existing = self.get_withdrawal(staging_id)
            if existing is not None:
                self._cleanup_active(staging_id, str(existing.get("extension") or extension))
                return {**existing, "already_withdrawn": True}
            receipt = {
                "staging_id": staging_id,
                "status": "withdrawn",
                "withdrawn_at": utc_now_iso(),
                "withdrawn_by": str(actor_id or "admin")[:200],
                "reason": str(reason or "").strip()[:500],
                "idempotency_key": idempotency_key,
                "extension": extension,
                "cleaned_resources": ["staged_binary", "staging_metadata", "staged_chunks"],
            }
            self._atomic_json(self._safe_child(self.withdrawn_dir, f"{staging_id}.json"), receipt)
            self._cleanup_active(staging_id, extension)
            return {**receipt, "already_withdrawn": False}

    def _cleanup_active(self, staging_id: str, extension: str) -> None:
        for path in (
            self._safe_child(self.files_dir, f"{staging_id}{extension}"),
            self._safe_child(self.files_dir, f".{staging_id}.uploading"),
            self._safe_child(self.metadata_dir, f"{staging_id}.json"),
            self._safe_child(self.metadata_dir, f"{staging_id}.json.tmp"),
            self._safe_child(self.chunks_dir, f"{staging_id}.json"),
            self._safe_child(self.chunks_dir, f"{staging_id}.json.tmp"),
        ):
            path.unlink(missing_ok=True)

    def _atomic_json(self, path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)

    @staticmethod
    def _safe_child(root: Path, name: str) -> Path:
        if not name or "/" in name or "\\" in name or ".." in name:
            raise AdminAPIError("DOCUMENT_STORAGE_INVALID", "Unsafe internal document storage name.", status_code=500)
        boundary = root.resolve()
        candidate = (boundary / name).resolve()
        try:
            candidate.relative_to(boundary)
        except ValueError as exc:
            raise AdminAPIError("DOCUMENT_STORAGE_INVALID", "Document storage escaped its root.", status_code=500) from exc
        return candidate

    @staticmethod
    def _validate_id(staging_id: str) -> str:
        value = str(staging_id or "").strip()
        if not _SAFE_STAGING_ID.fullmatch(value):
            raise AdminAPIError("DOCUMENT_STAGING_ID_INVALID", "Invalid staging identifier.", status_code=422)
        return value


class CanonicalKnowledgeAdapter:
    """Adapter over the existing parser, writer, and readback flow."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parents[3]).resolve()
        self.cfg = load_config(project_root=self.project_root)

    def document_by_sha256(self, digest: str) -> dict[str, Any] | None:
        connection = connect_mysql(self.cfg, autocommit=True)
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id, title, sha256, created_at FROM documents WHERE sha256=%s LIMIT 1", (digest,))
            row = cursor.fetchone()
            if not row:
                return None
            return {"document_id": int(row["id"]), "title": row.get("title"), "sha256": row.get("sha256")}
        finally:
            connection.close()

    def parse(self, path: Path, *, run_id: str) -> dict[str, Any]:
        return parse_external_source(path, self.cfg, run_id=run_id)

    def commit(self, item: dict[str, Any], parsed: dict[str, Any], *, run_id: str) -> dict[str, Any]:
        selected = [_selected_item(item)]
        return write_selected_documents(selected, {item["sha256"]: parsed}, self.cfg, run_id=run_id)

    def readback(self, item: dict[str, Any], *, expected_chunks: int) -> dict[str, Any]:
        payload = readback_external_ingestion(self.cfg, [_selected_item(item)], expected_unit_keys=[])
        document = next((value for value in payload.get("documents") or [] if value.get("sha256") == item["sha256"]), None)
        passed = bool(
            document
            and int(document.get("chunk_count") or 0) == int(expected_chunks)
            and int(document.get("empty_chunks") or 0) == 0
            and bool(document.get("source_hash_match"))
        )
        return {
            "passed": passed,
            "document_id": document.get("document_id") if document else None,
            "chunk_count": int(document.get("chunk_count") or 0) if document else 0,
            "provenance_ready": bool(document and document.get("source_hash_match")),
        }


class KnowledgeAdminService:
    def __init__(self, store: KnowledgeStagingStore, adapter: KnowledgeAdapter) -> None:
        self.store = store
        self.adapter = adapter
        self._lock = RLock()

    def upload(
        self,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        safe_name, extension = _validate_filename(filename)
        body = bytes(content or b"")
        if not body:
            raise AdminAPIError("DOCUMENT_EMPTY", "Empty documents are not accepted.", status_code=422)
        if len(body) > _MAX_UPLOAD_BYTES:
            raise AdminAPIError("DOCUMENT_TOO_LARGE", "Document exceeds the configured upload limit.", status_code=413)
        normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
        if normalized_mime not in DOCUMENT_MIME_TYPES[extension]:
            raise AdminAPIError("DOCUMENT_MIME_MISMATCH", "Document MIME type does not match its extension.", status_code=422)
        digest = sha256(body).hexdigest()
        duplicate_of: str | int | None = None
        for existing in self.store.list():
            if existing.get("sha256") == digest:
                duplicate_of = str(existing.get("staging_id"))
                break
        if duplicate_of is None:
            try:
                production = self.adapter.document_by_sha256(digest)
            except Exception:
                production = None
            if production:
                duplicate_of = int(production["document_id"])
        staging_id = self.store.new_id()
        path = self.store.store_file(staging_id, extension, body)
        now = utc_now_iso()
        record = {
            "staging_id": staging_id,
            "filename": safe_name,
            "extension": extension,
            "mime_type": normalized_mime or ("application/pdf" if extension == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "size_bytes": len(body),
            "sha256": digest,
            "status": "uploaded",
            "duplicate": duplicate_of is not None,
            "duplicate_of": duplicate_of,
            "parser_available": extension in SUPPORTED_DOCUMENT_EXTENSIONS,
            "security_scan": "not_configured",
            "ingested": False,
            "uploaded_at": now,
            "updated_at": now,
            "actor_id": str(actor_id or "admin")[:200],
            "_storage_file": str(path),
        }
        self.store.save(record)
        return _public_staging(record)

    def preflight(self, staging_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            record = self.store.get(staging_id)
            if record.get("duplicate"):
                raise AdminAPIError(
                    "DOCUMENT_DUPLICATE",
                    "The same document content already exists.",
                    status_code=409,
                    details={"duplicate_of": record.get("duplicate_of")},
                )
            if record.get("status") in {"preflight_passed", "dry_run_ready", "ingested"}:
                return _public_staging(record)
            run_id = f"admin-preflight-{uuid4().hex}"
            try:
                parsed = self.adapter.parse(self.store.file_path(record), run_id=run_id)
            except Exception as exc:
                record.update({"status": "preflight_failed", "error_code": "DOCUMENT_PARSE_FAILED", "updated_at": utc_now_iso()})
                self.store.save(record)
                raise AdminAPIError("DOCUMENT_PARSE_FAILED", "Document parsing failed.", status_code=422, details={"error_type": type(exc).__name__}) from exc
            if not parsed.get("quality_passed"):
                record.update({
                    "status": "preflight_failed",
                    "error_code": str(parsed.get("error") or "DOCUMENT_QUALITY_GATE_FAILED"),
                    "warnings": ["Text extraction did not pass the canonical quality gate."],
                    "updated_at": utc_now_iso(),
                })
                self.store.save(record)
                raise AdminAPIError("DOCUMENT_QUALITY_GATE_FAILED", "Extracted text did not pass the ingestion quality gate.", status_code=422)
            chunks = [_serialize_row(row) for row in parsed.get("rows") or []]
            self.store.save_chunks(staging_id, chunks)
            record.update({
                "status": "preflight_passed",
                "preflight": {
                    "parser": parsed.get("parser"),
                    "page_count": parsed.get("page_count"),
                    "character_count": int(parsed.get("character_count") or 0),
                    "estimated_chunk_count": len(chunks),
                    "garbled_ratio": parsed.get("garbled_ratio"),
                    "warnings": [],
                    "text_extraction": "passed",
                    "security_scan": "not_configured",
                },
                "parser_available": True,
                "updated_at": utc_now_iso(),
                "preflight_actor": str(actor_id or "admin")[:200],
            })
            self.store.save(record)
            payload = _public_staging(record)
            payload["production_write"] = False
            return payload

    def dry_run(self, staging_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            record = self.store.get(staging_id)
            if record.get("status") == "ingested":
                return dict(record.get("commit_receipt") or {})
            if record.get("status") == "uploaded":
                self.preflight(staging_id, actor_id=actor_id)
                record = self.store.get(staging_id)
            if record.get("status") not in {"preflight_passed", "dry_run_ready"}:
                raise AdminAPIError("DOCUMENT_NOT_READY", "Document preflight must pass before dry-run.", status_code=409)
            chunks = self.store.load_chunks(staging_id)
            candidate_summary = _candidate_summary(chunks)
            record.update({"status": "dry_run_ready", "updated_at": utc_now_iso(), "dry_run_actor": str(actor_id or "admin")[:200]})
            self.store.save(record)
            return {
                **_public_staging(record),
                **candidate_summary,
                "total_characters": sum(int(item.get("char_len") or len(str(item.get("text") or ""))) for item in chunks),
                "production_write": False,
                "index_modified": False,
                "items": [_chunk_summary(item) for item in chunks[:20]],
            }

    def list_staged_chunks(
        self,
        staging_id: str,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
        page_number: int | None = None,
        section: str | None = None,
    ) -> dict[str, Any]:
        self.store.get(staging_id)
        all_items = self.store.load_chunks(staging_id)
        items = list(all_items)
        keyword = str(query or "").strip().casefold()
        section_filter = str(section or "").strip().casefold()
        if keyword:
            items = [item for item in items if keyword in str(item.get("text") or "").casefold()]
        if page_number is not None:
            items = [item for item in items if item.get("page_start") == page_number or item.get("page_end") == page_number]
        if section_filter:
            items = [item for item in items if section_filter in str(item.get("section_path") or "").casefold()]
        current = max(1, int(page))
        limit = max(1, min(int(page_size), 100))
        offset = (current - 1) * limit
        return {
            "items": [_chunk_summary(item) for item in items[offset:offset + limit]],
            "total": len(items),
            "page": current,
            "page_size": limit,
            "candidate_summary": _candidate_summary(all_items),
        }

    def get_staged_chunk(self, staging_id: str, chunk_index: int) -> dict[str, Any]:
        self.store.get(staging_id)
        item = next((row for row in self.store.load_chunks(staging_id) if int(row.get("chunk_index") or 0) == int(chunk_index)), None)
        if item is None:
            raise AdminAPIError("DOCUMENT_CHUNK_NOT_FOUND", "Staged chunk was not found.", status_code=404)
        return _chunk_detail(item)

    def edit_staged_chunk(
        self,
        staging_id: str,
        chunk_index: int,
        *,
        effective_text: str,
        reason: str,
        actor_id: str,
        base_version: int,
        idempotency_key: str,
        revision_source: str = "manual_staged_edit",
    ) -> dict[str, Any]:
        with self._lock:
            record = self.store.get(staging_id)
            if record.get("status") != "dry_run_ready":
                raise AdminAPIError("DOCUMENT_NOT_READY", "Dry-run must complete before editing chunks.", status_code=409)
            chunks = self.store.load_chunks(staging_id)
            item = next((row for row in chunks if int(row.get("chunk_index") or 0) == int(chunk_index)), None)
            if item is None:
                raise AdminAPIError("DOCUMENT_CHUNK_NOT_FOUND", "Staged chunk was not found.", status_code=404)
            current_version = int(item.get("edit_version") or 0)
            key = str(idempotency_key or "").strip()
            if not key or len(key) > 200:
                raise AdminAPIError("IDEMPOTENCY_KEY_INVALID", "A valid idempotency key is required.", status_code=422)
            revisions = [dict(value) for value in item.get("staged_revisions") or [] if isinstance(value, Mapping)]
            requested_text = _validate_effective_text(effective_text)
            requested_hash = sha256(requested_text.encode("utf-8")).hexdigest()
            prior = next((value for value in revisions if value.get("idempotency_key") == key), None)
            if prior:
                if str(prior.get("after_hash") or "") != requested_hash:
                    raise AdminAPIError("IDEMPOTENCY_CONFLICT", "The idempotency key was already used for another edit.", status_code=409)
                return _chunk_detail(item)
            if int(base_version) != current_version:
                raise AdminAPIError("STAGED_CHUNK_CONFLICT", "The staged chunk changed after it was opened.", status_code=409)
            raw_text = str(item.get("raw_text") if item.get("raw_text") is not None else item.get("text") or "")
            current_text = str(item.get("effective_text") if item.get("effective_text") is not None else item.get("text") or "")
            if requested_text == current_text:
                return _chunk_detail(item)
            now = utc_now_iso()
            revisions.append({
                "revision_id": f"staged-rev-{uuid4().hex}",
                "base_version": current_version,
                "version": current_version + 1,
                "before_hash": sha256(current_text.encode("utf-8")).hexdigest(),
                "after_hash": requested_hash,
                "before_text": current_text,
                "after_text": requested_text,
                "editor": str(actor_id or "admin")[:200],
                "reason": str(reason or "").strip()[:500],
                "edited_at": now,
                "idempotency_key": key,
                "source": str(revision_source or "manual_staged_edit")[:80],
            })
            item.update({
                "raw_text": raw_text,
                "effective_text": requested_text,
                "text": requested_text,
                "char_len": len(requested_text),
                "content_hash": requested_hash,
                "edit_state": "edited" if requested_text != raw_text else "clean",
                "edit_version": current_version + 1,
                "staged_revisions": revisions,
                "quality": analyze_chunk_quality(requested_text, chunk_type=str(item.get("chunk_type") or "text")),
            })
            self.store.save_chunks(staging_id, chunks)
            return _chunk_detail(item)

    def exclude_staged_chunk(
        self,
        staging_id: str,
        chunk_index: int,
        *,
        reason: str,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._set_staged_chunk_participation(
            staging_id,
            chunk_index,
            participation_state="excluded",
            reason=reason,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )

    def restore_staged_chunk_inclusion(
        self,
        staging_id: str,
        chunk_index: int,
        *,
        reason: str,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._set_staged_chunk_participation(
            staging_id,
            chunk_index,
            participation_state="included",
            reason=reason,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )

    def _set_staged_chunk_participation(
        self,
        staging_id: str,
        chunk_index: int,
        *,
        participation_state: str,
        reason: str,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self.store.get(staging_id)
            if record.get("status") != "dry_run_ready":
                raise AdminAPIError("DOCUMENT_NOT_READY", "Dry-run must complete before changing chunk participation.", status_code=409)
            chunks = self.store.load_chunks(staging_id)
            item = next((row for row in chunks if int(row.get("chunk_index") or 0) == int(chunk_index)), None)
            if item is None:
                raise AdminAPIError("DOCUMENT_CHUNK_NOT_FOUND", "Staged chunk was not found.", status_code=404)
            key = _validate_idempotency_key(idempotency_key)
            events = [dict(value) for value in item.get("participation_events") or [] if isinstance(value, Mapping)]
            prior = next((value for value in events if value.get("idempotency_key") == key), None)
            if prior:
                if prior.get("participation_state") != participation_state:
                    raise AdminAPIError("IDEMPOTENCY_CONFLICT", "The idempotency key was already used for another lifecycle action.", status_code=409)
                return _chunk_detail(item)
            if _participation_state(item) == participation_state:
                return _chunk_detail(item)
            version = int(item.get("participation_version") or 0) + 1
            events.append({
                "event_id": f"staged-participation-{uuid4().hex}",
                "participation_state": participation_state,
                "version": version,
                "actor": str(actor_id or "admin")[:200],
                "reason": str(reason or "").strip()[:500],
                "changed_at": utc_now_iso(),
                "idempotency_key": key,
            })
            item.update({
                "participation_state": participation_state,
                "participation_version": version,
                "participation_events": events,
            })
            self.store.save_chunks(staging_id, chunks)
            return _chunk_detail(item)

    def restore_staged_chunk(
        self,
        staging_id: str,
        chunk_index: int,
        *,
        reason: str,
        actor_id: str,
        base_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        item = self.get_staged_chunk(staging_id, chunk_index)
        return self.edit_staged_chunk(
            staging_id,
            chunk_index,
            effective_text=str(item["raw_text"]),
            reason=reason,
            actor_id=actor_id,
            base_version=base_version,
            idempotency_key=idempotency_key,
            revision_source="restore_parser_output",
        )

    def commit(self, staging_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            record = self.store.get(staging_id)
            if record.get("status") == "ingested" and isinstance(record.get("commit_receipt"), dict):
                return dict(record["commit_receipt"])
            if record.get("status") != "dry_run_ready":
                raise AdminAPIError("DOCUMENT_NOT_READY", "Preflight and dry-run must complete before commit.", status_code=409)
            chunks = self.store.load_chunks(staging_id)
            candidates = [item for item in chunks if _participation_state(item) == "included"]
            candidate_summary = _candidate_summary(chunks)
            if not candidates:
                raise AdminAPIError(
                    "DOCUMENT_NO_COMMIT_CANDIDATES",
                    "The staged document has no content selected for ingestion.",
                    status_code=409,
                )
            parsed = {
                "quality_passed": True,
                "title": Path(str(record.get("filename") or "document")).stem,
                "mime": record.get("mime_type"),
                "chunk_count": len(candidates),
                "rows": [_row_from_dict(item) for item in candidates],
            }
            item = dict(record)
            item["absolute_path"] = str(self.store.file_path(record))
            item["relative_path"] = str(record.get("filename") or "document")
            run_id = f"admin-commit-{uuid4().hex}"
            write_result = self.adapter.commit(item, parsed, run_id=run_id)
            if write_result.get("failed_documents"):
                raise AdminAPIError("DOCUMENT_INGESTION_FAILED", "Canonical ingestion writer rejected the document.", status_code=500)
            readback = self.adapter.readback(item, expected_chunks=len(candidates))
            if not readback.get("passed"):
                raise AdminAPIError("DOCUMENT_READBACK_FAILED", "Document write could not be verified by readback.", status_code=500)
            receipt = {
                "staging_id": staging_id,
                "status": "ingested",
                "ingested": True,
                "document_id": readback.get("document_id"),
                "chunk_count": int(readback.get("chunk_count") or 0),
                **candidate_summary,
                "readback": dict(readback),
                "index_release": "pending",
                "production_index_modified": False,
                "completed_at": utc_now_iso(),
            }
            record.update({"status": "ingested", "ingested": True, "commit_receipt": receipt, "updated_at": utc_now_iso(), "commit_actor": str(actor_id or "admin")[:200]})
            self.store.save(record)
            return receipt

    def withdraw_staging(
        self,
        staging_id: str,
        *,
        reason: str,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        key = _validate_idempotency_key(idempotency_key)
        with self._lock:
            withdrawn = self.store.get_withdrawal(staging_id)
            if withdrawn is not None:
                return {**withdrawn, "already_withdrawn": True}
            record = self.store.get(staging_id)
            if record.get("status") == "ingested" or record.get("ingested") is True:
                raise AdminAPIError(
                    "DOCUMENT_ALREADY_COMMITTED",
                    "The document has already been ingested and cannot be withdrawn from staging.",
                    status_code=409,
                )
            return self.store.withdraw(record, actor_id=actor_id, reason=reason, idempotency_key=key)

    def list_staging(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for record in self.store.list():
            item = _public_staging(record)
            chunks = self.store.load_chunks(str(record.get("staging_id") or ""))
            if chunks or record.get("status") in {"preflight_passed", "dry_run_ready", "ingested"}:
                item.update(_candidate_summary(chunks))
            items.append(item)
        return {"items": items, "total": len(items), "persistence": "host_local_file_backed"}


def _validate_filename(filename: str) -> tuple[str, str]:
    raw = str(filename or "").strip()
    windows = PureWindowsPath(raw)
    if not raw or windows.is_absolute() or windows.drive or PurePosixPath(raw).is_absolute() or ".." in raw or "/" in raw or "\\" in raw:
        raise AdminAPIError("DOCUMENT_FILENAME_INVALID", "Document filename must not contain a path.", status_code=422)
    extension = Path(raw).suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise AdminAPIError("DOCUMENT_TYPE_UNSUPPORTED", "Only canonical PDF and DOCX parsers are supported.", status_code=422)
    safe = re.sub(r"[^A-Za-z0-9._()\-\u4e00-\u9fff]+", "_", raw).strip(" ._")
    if not safe:
        safe = f"document{extension}"
    if not safe.lower().endswith(extension):
        safe += extension
    return safe[:220], extension


def _serialize_row(row: Any) -> dict[str, Any]:
    if is_dataclass(row):
        raw = asdict(row)
    elif isinstance(row, Mapping):
        raw = dict(row)
    else:
        raw = {name: getattr(row, name, None) for name in (
            "chunk_index", "page_start", "page_end", "chunk_type", "section_path", "text", "char_len",
            "token_len", "content_hash", "quality_score", "meta_json", "is_active",
        )}
    text = str(raw.get("text") or "")
    quality = analyze_chunk_quality(text, chunk_type=str(raw.get("chunk_type") or "text"))
    return {
        "chunk_index": int(raw.get("chunk_index") or 0),
        "page_start": raw.get("page_start"),
        "page_end": raw.get("page_end"),
        "chunk_type": str(raw.get("chunk_type") or "text"),
        "section_path": raw.get("section_path"),
        "text": text,
        "raw_text": text,
        "effective_text": text,
        "char_len": int(raw.get("char_len") or len(text)),
        "token_len": raw.get("token_len"),
        "content_hash": raw.get("content_hash") or sha256(text.encode("utf-8")).hexdigest(),
        "quality_score": raw.get("quality_score"),
        "meta_json": raw.get("meta_json") if isinstance(raw.get("meta_json"), (dict, list, str)) else {},
        "is_active": int(raw.get("is_active", 1)),
        "edit_state": "clean",
        "edit_version": 0,
        "staged_revisions": [],
        "participation_state": "included",
        "participation_version": 0,
        "participation_events": [],
        "quality": quality,
    }


def _row_from_dict(item: Mapping[str, Any]) -> ChunkInsertRow:
    raw_text = str(item.get("raw_text") if item.get("raw_text") is not None else item.get("text") or "")
    effective_text = str(item.get("effective_text") if item.get("effective_text") is not None else item.get("text") or "")
    metadata = item.get("meta_json")
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    metadata["knowledge_correction"] = {
        "raw_text": raw_text,
        "raw_text_hash": sha256(raw_text.encode("utf-8")).hexdigest(),
        "effective_text_hash": sha256(effective_text.encode("utf-8")).hexdigest(),
        "staged_revisions": [dict(value) for value in item.get("staged_revisions") or [] if isinstance(value, Mapping)],
    }
    return ChunkInsertRow(
        chunk_index=int(item.get("chunk_index") or 0),
        page_start=item.get("page_start"),
        page_end=item.get("page_end"),
        chunk_type=str(item.get("chunk_type") or "text"),
        text=effective_text,
        char_len=len(effective_text),
        token_len=item.get("token_len"),
        section_path=item.get("section_path"),
        content_hash=sha256(effective_text.encode("utf-8")).hexdigest(),
        quality_score=item.get("quality_score"),
        meta_json=metadata,
        is_active=int(item.get("is_active", 1)),
    )


def _public_staging(record: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "staging_id", "filename", "extension", "mime_type", "size_bytes", "sha256", "status", "duplicate",
        "duplicate_of", "parser_available", "security_scan", "ingested", "uploaded_at", "updated_at", "preflight",
        "error_code", "warnings", "commit_receipt",
    }
    return {key: value for key, value in record.items() if key in allowed}


def _chunk_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    text = str(item.get("effective_text") if item.get("effective_text") is not None else item.get("text") or "")
    return {
        "chunk_index": int(item.get("chunk_index") or 0),
        "page_start": item.get("page_start"),
        "page_end": item.get("page_end"),
        "section": item.get("section_path"),
        "chunk_type": item.get("chunk_type"),
        "preview": re.sub(r"\s+", " ", text).strip()[:320],
        "length": int(item.get("char_len") or len(text)),
        "provenance": {"page_start": item.get("page_start"), "page_end": item.get("page_end"), "section": item.get("section_path")},
        "edit_state": str(item.get("edit_state") or "clean"),
        "participation_state": _participation_state(item),
        "included": _participation_state(item) == "included",
        "version": int(item.get("edit_version") or 0),
        "quality": item.get("quality") or analyze_chunk_quality(text, chunk_type=str(item.get("chunk_type") or "text")),
    }


def _chunk_detail(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_text = str(item.get("raw_text") if item.get("raw_text") is not None else item.get("text") or "")
    effective_text = str(item.get("effective_text") if item.get("effective_text") is not None else item.get("text") or "")
    return {
        **_chunk_summary(item),
        "text": effective_text,
        "raw_text": raw_text,
        "effective_text": effective_text,
        "metadata": item.get("meta_json") or {},
        "revisions": [dict(value) for value in item.get("staged_revisions") or [] if isinstance(value, Mapping)],
        "participation_history": [dict(value) for value in item.get("participation_events") or [] if isinstance(value, Mapping)],
    }


def _participation_state(item: Mapping[str, Any]) -> str:
    return "excluded" if str(item.get("participation_state") or "included") == "excluded" else "included"


def _candidate_summary(chunks: list[Mapping[str, Any]]) -> dict[str, int]:
    total = len(chunks)
    excluded = sum(1 for item in chunks if _participation_state(item) == "excluded")
    quality_states = [
        str(quality.get("state") or "normal")
        for item in chunks
        for quality in [item.get("quality") if isinstance(item.get("quality"), Mapping) else {}]
    ]
    return {
        "total_chunks": total,
        "included_chunks": total - excluded,
        "excluded_chunks": excluded,
        "review_recommended_chunks": sum(1 for state in quality_states if state != "normal"),
        "suspected_parse_error_chunks": sum(1 for state in quality_states if state == "suspected_parse_error"),
    }


def _validate_idempotency_key(value: str) -> str:
    key = str(value or "").strip()
    if not key or len(key) > 200:
        raise AdminAPIError("IDEMPOTENCY_KEY_INVALID", "A valid idempotency key is required.", status_code=422)
    return key


def _validate_effective_text(value: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise AdminAPIError("CHUNK_TEXT_EMPTY", "Chunk text must not be empty.", status_code=422)
    if len(text) > 1_000_000:
        raise AdminAPIError("CHUNK_TEXT_TOO_LARGE", "Chunk text exceeds the correction limit.", status_code=422)
    return text


def _selected_item(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "absolute_path": str(item["absolute_path"]),
        "relative_path": str(item.get("relative_path") or item.get("filename") or "document"),
        "filename": str(item.get("filename") or "document"),
        "sha256": str(item["sha256"]),
        "excluded": False,
    }


_DEFAULT_SERVICE: KnowledgeAdminService | None = None


def get_knowledge_admin_service() -> KnowledgeAdminService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        project_root = Path(__file__).resolve().parents[3]
        _DEFAULT_SERVICE = KnowledgeAdminService(
            KnowledgeStagingStore(project_root / "runtime" / "admin_console" / "knowledge"),
            CanonicalKnowledgeAdapter(project_root),
        )
    return _DEFAULT_SERVICE


__all__ = [
    "CanonicalKnowledgeAdapter",
    "KnowledgeAdminService",
    "KnowledgeStagingStore",
    "SUPPORTED_DOCUMENT_EXTENSIONS",
    "get_knowledge_admin_service",
]
