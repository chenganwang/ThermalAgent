from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

from services.ingest_service.external_ingestion import connect_mysql
from services.ingest_service.knowledge.quality import analyze_chunk_quality
from services.retrieval_service.config import load_config

from ..contracts import AdminAPIError


@dataclass(frozen=True)
class DocumentContentResource:
    path: Path
    filename: str
    media_type: str
    size_bytes: int | None = None
    sha256: str | None = None


class DocumentAdminRepository:
    """SELECT-only projection over the canonical ThermalAgent schema."""

    _SORTS = {
        "created_desc": "d.created_at DESC, d.id DESC",
        "created_asc": "d.created_at ASC, d.id ASC",
        "updated_desc": "d.updated_at DESC, d.id DESC",
        "title_asc": "d.title ASC, d.id ASC",
        "title_desc": "d.title DESC, d.id DESC",
    }

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parents[3]).resolve()
        self.cfg = load_config(project_root=self.project_root)
        configured_roots = [item.strip() for item in os.getenv("ADMIN_DOCUMENT_CONTENT_ROOTS", "").split(os.pathsep) if item.strip()]
        self.hash_search_roots = tuple(dict.fromkeys(Path(item).resolve() for item in configured_roots))
        self.content_roots = tuple(dict.fromkeys([
            self.project_root,
            *self.hash_search_roots,
        ]))

    def statistics(self) -> dict[str, int | None]:
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            counts: dict[str, int | None] = {}
            for table in ("documents", "chunks", "knowledge_units"):
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s",
                    (table,),
                )
                if int((cursor.fetchone() or {}).get("n") or 0) <= 0:
                    counts[table] = None
                    continue
                cursor.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                counts[table] = int((cursor.fetchone() or {}).get("n") or 0)
            return counts
        finally:
            connection.close()

    def find_document_by_hash(self, digest: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id, title, sha256 FROM documents WHERE sha256=%s LIMIT 1", (str(digest).lower(),))
            row = cursor.fetchone()
            return _document_identity(row) if row else None
        finally:
            connection.close()

    def list_documents(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        sort: str = "created_desc",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        keyword = str(query or "").strip()
        if keyword:
            where.append("(d.title LIKE %s OR d.source LIKE %s)")
            term = f"%{keyword}%"
            params.extend((term, term))
        if source_type:
            where.append("d.doc_type=%s")
            params.append(str(source_type))
        if status == "active":
            where.append("EXISTS (SELECT 1 FROM chunks cx WHERE cx.doc_id=d.id AND cx.is_active=1)")
        elif status == "inactive":
            where.append("NOT EXISTS (SELECT 1 FROM chunks cx WHERE cx.doc_id=d.id AND cx.is_active=1)")
        order = self._SORTS.get(sort, self._SORTS["created_desc"])
        current = max(1, int(page))
        limit = max(1, min(int(page_size), 100))
        offset = (current - 1) * limit
        clause = " AND ".join(where)
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(f"SELECT COUNT(*) AS n FROM documents d WHERE {clause}", tuple(params))
            total = int((cursor.fetchone() or {}).get("n") or 0)
            cursor.execute(
                f"""
                SELECT d.id, d.title, d.source, d.mime, d.doc_type, d.language, d.sha256,
                       d.created_at, d.updated_at,
                       COUNT(c.id) AS chunk_count,
                       SUM(CASE WHEN c.is_active=1 THEN 1 ELSE 0 END) AS active_chunk_count,
                       MAX(c.page_end) AS pages
                FROM documents d LEFT JOIN chunks c ON c.doc_id=d.id
                WHERE {clause}
                GROUP BY d.id, d.title, d.source, d.mime, d.doc_type, d.language, d.sha256, d.created_at, d.updated_at
                ORDER BY {order} LIMIT %s OFFSET %s
                """,
                tuple(params + [limit, offset]),
            )
            items = [_document_summary(row) for row in cursor.fetchall() or []]
            return {"items": items, "total": total, "page": current, "page_size": limit}
        finally:
            connection.close()

    def get_document(self, document_id: int) -> dict[str, Any]:
        doc_id = _document_id(document_id)
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT d.id, d.title, d.source, d.mime, d.doc_type, d.organization, d.language, d.publish_year,
                       d.url, d.sha256, d.is_public, d.license_note, d.meta_json, d.created_at, d.updated_at,
                       COUNT(c.id) AS chunk_count, SUM(CASE WHEN c.is_active=1 THEN 1 ELSE 0 END) AS active_chunk_count,
                       MAX(c.page_end) AS pages
                FROM documents d LEFT JOIN chunks c ON c.doc_id=d.id
                WHERE d.id=%s GROUP BY d.id
                """,
                (doc_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise AdminAPIError("DOCUMENT_NOT_FOUND", "Document was not found.", status_code=404)
            payload = _document_summary(row)
            meta = _json_object(row.get("meta_json"))
            original_file = self._original_file_status(cursor, row)
            payload.update({
                "organization": row.get("organization"),
                "publish_year": row.get("publish_year"),
                "public": bool(row.get("is_public")),
                "license_note": row.get("license_note"),
                "parser": meta.get("parser") or meta.get("parser_name"),
                "provenance": {
                    "source_name": Path(str(row.get("source") or "")).name or str(row.get("source") or ""),
                    "source_hash": row.get("sha256"),
                    "ingestion_run_id": meta.get("external_ingestion_run_id"),
                },
                 "original_available": bool(original_file["available"]),
                 "original_file": original_file,
                 "content_quality": self._document_quality(cursor, doc_id),
                 "index_status": self._document_index_status(cursor, doc_id),
             })
            return payload
        finally:
            connection.close()

    def list_chunks(
        self,
        document_id: int,
        *,
        query: str | None = None,
        page_number: int | None = None,
        section: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        doc_id = _document_id(document_id)
        where = ["doc_id=%s"]
        params: list[Any] = [doc_id]
        if query:
            where.append("text LIKE %s")
            params.append(f"%{str(query).strip()}%")
        if page_number is not None:
            where.append("(page_start=%s OR page_end=%s OR (page_start<=%s AND page_end>=%s))")
            params.extend((page_number, page_number, page_number, page_number))
        if section:
            where.append("section_path LIKE %s")
            params.append(f"%{str(section).strip()}%")
        clause = " AND ".join(where)
        current = max(1, int(page))
        limit = max(1, min(int(page_size), 100))
        offset = (current - 1) * limit
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(f"SELECT COUNT(*) AS n FROM chunks WHERE {clause}", tuple(params))
            total = int((cursor.fetchone() or {}).get("n") or 0)
            cursor.execute(
                f"""
                SELECT id, chunk_index, page_start, page_end, chunk_type, section_path, text, char_len,
                       token_len, quality_score, meta_json, is_active, created_at, updated_at
                FROM chunks WHERE {clause} ORDER BY chunk_index LIMIT %s OFFSET %s
                """,
                tuple(params + [limit, offset]),
            )
            return {"items": [_chunk_summary(row) for row in cursor.fetchall() or []], "total": total, "page": current, "page_size": limit}
        finally:
            connection.close()

    def get_chunk(self, document_id: int, chunk_id: int) -> dict[str, Any]:
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, chunk_index, page_start, page_end, chunk_type, section_path, text, char_len, token_len, quality_score, meta_json, is_active, created_at, updated_at FROM chunks WHERE id=%s AND doc_id=%s LIMIT 1",
                (int(chunk_id), _document_id(document_id)),
            )
            row = cursor.fetchone()
            if not row:
                raise AdminAPIError("DOCUMENT_CHUNK_NOT_FOUND", "Document chunk was not found.", status_code=404)
            return {**_chunk_summary(row), "text": str(row.get("text") or ""), "metadata": _safe_metadata(_json_object(row.get("meta_json")))}
        finally:
            connection.close()

    def resolve_content(self, document_id: int) -> DocumentContentResource:
        doc_id = _document_id(document_id)
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id, title, source, local_path, mime FROM documents WHERE id=%s LIMIT 1", (doc_id,))
            row = cursor.fetchone()
            if not row:
                raise AdminAPIError("DOCUMENT_NOT_FOUND", "Document was not found.", status_code=404)
            resource = self._content_resource(cursor, row, required=True)
            assert resource is not None
            return resource
        finally:
            connection.close()

    def list_knowledge_units(self, *, status: str | None = None, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if status:
            where.append("review_status=%s")
            params.append(str(status))
        current = max(1, int(page))
        limit = max(1, min(int(page_size), 100))
        offset = (current - 1) * limit
        clause = " AND ".join(where)
        connection = self._connect()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(f"SELECT COUNT(*) AS n FROM knowledge_units WHERE {clause}", tuple(params))
            total = int((cursor.fetchone() or {}).get("n") or 0)
            cursor.execute(
                f"SELECT id, unit_code, unit_type, title, summary, source_doc_id, source_chunk_id, review_status, confidence_score, created_at, updated_at FROM knowledge_units WHERE {clause} ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s",
                tuple(params + [limit, offset]),
            )
            items = [{
                "id": int(row["id"]), "unit_code": row.get("unit_code"), "unit_type": row.get("unit_type"),
                "title": row.get("title"), "summary": row.get("summary"), "document_id": row.get("source_doc_id"),
                "chunk_id": row.get("source_chunk_id"), "status": row.get("review_status"),
                "confidence": row.get("confidence_score"), "created_at": _iso(row.get("created_at")), "updated_at": _iso(row.get("updated_at")),
                "release_boundary": "shadow_only",
            } for row in cursor.fetchall() or []]
            return {"items": items, "total": total, "page": current, "page_size": limit, "read_only": True, "production_active": False}
        finally:
            connection.close()

    def _content_resource(self, cursor: Any, document: dict[str, Any], *, required: bool) -> DocumentContentResource | None:
        expected_document_hash = str(document.get("sha256") or "").strip().lower()
        cursor.execute(
            "SELECT id, chunk_id, asset_type, title, file_path, asset_meta "
            "FROM source_assets WHERE doc_id=%s AND chunk_id IS NULL ORDER BY id",
            (int(document["id"]),),
        )
        direct_assets = [
            dict(row)
            for row in (cursor.fetchall() or [])
            if str(row.get("asset_type") or "") == "document_source"
        ]
        direct_resources: dict[Path, DocumentContentResource] = {}
        integrity_error = False
        for asset in direct_assets:
            raw = str(asset.get("file_path") or "")
            candidate = Path(raw)
            if not candidate.is_absolute():
                continue
            try:
                path = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not path.is_file():
                continue
            metadata = _json_object(asset.get("asset_meta"))
            asset_hash = str(metadata.get("sha256") or "").strip().lower()
            actual_hash = _sha256_file(path)
            expected_hashes = {value for value in (expected_document_hash, asset_hash) if value}
            if len(expected_hashes) > 1 or (expected_hashes and actual_hash not in expected_hashes):
                integrity_error = True
                continue
            filename = _safe_download_filename(asset.get("title") or path.name, fallback=f"document-{document['id']}")
            media = str(document.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
            direct_resources[path] = DocumentContentResource(
                path=path,
                filename=filename,
                media_type=media,
                size_bytes=path.stat().st_size,
                sha256=actual_hash,
            )
        if integrity_error:
            raise AdminAPIError(
                "SOURCE_ASSET_INTEGRITY_MISMATCH",
                "Original document integrity verification failed.",
                status_code=409,
            )
        if len(direct_resources) > 1:
            raise AdminAPIError(
                "ORIGINAL_ASSET_AMBIGUOUS",
                "More than one verified original document asset is available.",
                status_code=409,
            )
        if direct_resources:
            return next(iter(direct_resources.values()))

        candidates: list[str] = []
        if document.get("local_path"):
            candidates.append(str(document["local_path"]))
        source = str(document.get("source") or "")
        if source and not source.lower().startswith(("http://", "https://")):
            candidates.append(source)
        for raw in candidates:
            if not raw:
                continue
            try:
                path = Path(raw).resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not path.is_file():
                continue
            if not any(_is_relative_to(path, root) for root in self.content_roots):
                continue
            actual_hash = _sha256_file(path)
            if expected_document_hash and actual_hash != expected_document_hash:
                raise AdminAPIError(
                    "SOURCE_ASSET_INTEGRITY_MISMATCH",
                    "Original document integrity verification failed.",
                    status_code=409,
                )
            filename = _safe_download_filename(path.name, fallback=f"document-{document['id']}")
            media = str(document.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
            return DocumentContentResource(
                path=path,
                filename=filename,
                media_type=media,
                size_bytes=path.stat().st_size,
                sha256=actual_hash,
            )
        if expected_document_hash and self.hash_search_roots:
            hash_matches: dict[Path, DocumentContentResource] = {}
            for root in self.hash_search_roots:
                if not root.is_dir():
                    continue
                for pattern in ("*.pdf", "*.docx"):
                    try:
                        paths = root.rglob(pattern)
                        for path in paths:
                            try:
                                resolved = path.resolve(strict=True)
                                if not resolved.is_file() or _sha256_file(resolved) != expected_document_hash:
                                    continue
                            except (OSError, RuntimeError):
                                continue
                            filename = _safe_download_filename(resolved.name, fallback=f"document-{document['id']}")
                            media = str(document.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
                            hash_matches[resolved] = DocumentContentResource(
                                path=resolved,
                                filename=filename,
                                media_type=media,
                                size_bytes=resolved.stat().st_size,
                                sha256=expected_document_hash,
                            )
                    except OSError:
                        continue
            if len(hash_matches) > 1:
                raise AdminAPIError(
                    "ORIGINAL_ASSET_AMBIGUOUS",
                    "More than one verified original document asset is available.",
                    status_code=409,
                )
            if hash_matches:
                return next(iter(hash_matches.values()))
        if required:
            raise AdminAPIError("ORIGINAL_ASSET_NOT_AVAILABLE", "Original document content is not available.", status_code=404)
        return None

    def _original_file_status(self, cursor: Any, document: dict[str, Any]) -> dict[str, Any]:
        try:
            resource = self._content_resource(cursor, document, required=False)
        except AdminAPIError as exc:
            reasons = {
                "SOURCE_ASSET_INTEGRITY_MISMATCH": "integrity_error",
                "ORIGINAL_ASSET_AMBIGUOUS": "ambiguous",
            }
            return {
                "available": False,
                "open_supported": False,
                "download_supported": False,
                "state": reasons.get(exc.code, "unavailable"),
                "reason": reasons.get(exc.code, "unavailable"),
            }
        if resource is None:
            return {
                "available": False,
                "open_supported": False,
                "download_supported": False,
                "state": "unavailable",
                "reason": "unavailable",
            }
        return {
            "available": True,
            "open_supported": resource.media_type == "application/pdf",
            "download_supported": True,
            "state": "available",
            "reason": None,
        }

    @staticmethod
    def _document_quality(cursor: Any, document_id: int) -> dict[str, int]:
        cursor.execute("SELECT text, chunk_type FROM chunks WHERE doc_id=%s ORDER BY chunk_index", (int(document_id),))
        counts = {"normal": 0, "needs_review": 0, "suspected_parse_error": 0}
        for row in cursor.fetchall() or []:
            result = analyze_chunk_quality(
                str(row.get("text") or ""),
                chunk_type=str(row.get("chunk_type") or "text"),
            )
            state = str(result.get("state") or "needs_review")
            counts[state if state in counts else "needs_review"] += 1
        return counts

    @staticmethod
    def _document_index_status(cursor: Any, document_id: int) -> dict[str, Any]:
        cursor.execute("SELECT meta_json FROM chunks WHERE doc_id=%s AND is_active=1", (int(document_id),))
        counts = {"synced": 0, "stale": 0, "candidate": 0, "releasing": 0, "failed": 0}
        for row in cursor.fetchall() or []:
            metadata = _json_object(row.get("meta_json"))
            correction = metadata.get("knowledge_correction")
            state = str(correction.get("index_status") or "synced") if isinstance(correction, dict) else "synced"
            counts[state if state in counts else "stale"] += 1
        state = "failed" if counts["failed"] else "releasing" if counts["releasing"] else "candidate" if counts["candidate"] else "stale" if counts["stale"] else "synced"
        return {"state": state, "counts": counts, "stale_chunks": counts["stale"]}

    def _connect(self) -> Any:
        try:
            return connect_mysql(self.cfg, autocommit=True)
        except Exception as exc:
            raise AdminAPIError("DATABASE_UNAVAILABLE", "Document repository is unavailable.", status_code=503, retryable=True) from exc


def _document_id(value: int) -> int:
    doc_id = int(value)
    if doc_id <= 0:
        raise AdminAPIError("DOCUMENT_ID_INVALID", "Invalid document identifier.", status_code=422)
    return doc_id


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_download_filename(value: Any, *, fallback: str) -> str:
    name = Path(str(value or "").replace("\r", "").replace("\n", "")).name.strip(" .")
    return name[:220] if name else fallback


def _document_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {"document_id": int(row["id"]), "title": row.get("title"), "sha256": row.get("sha256")}


def _document_summary(row: dict[str, Any]) -> dict[str, Any]:
    source = str(row.get("source") or "")
    return {
        "document_id": int(row["id"]),
        "title": row.get("title"),
        "filename": Path(source).name or row.get("title"),
        "source_type": row.get("doc_type"),
        "mime_type": row.get("mime"),
        "language": row.get("language"),
        "sha256": row.get("sha256"),
        "pages": int(row.get("pages") or 0) or None,
        "chunks": int(row.get("chunk_count") or 0),
        "status": "active" if int(row.get("active_chunk_count") or 0) > 0 else "inactive",
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _chunk_summary(row: dict[str, Any]) -> dict[str, Any]:
    text = str(row.get("text") or "")
    quality = analyze_chunk_quality(text, chunk_type=str(row.get("chunk_type") or "text"))
    metadata = _json_object(row.get("meta_json"))
    correction = metadata.get("knowledge_correction")
    index_status = str(correction.get("index_status") or "synced") if isinstance(correction, dict) else "synced"
    return {
        "chunk_id": int(row["id"]), "chunk_index": int(row.get("chunk_index") or 0),
        "page_start": row.get("page_start"), "page_end": row.get("page_end"),
        "section": row.get("section_path"), "chunk_type": row.get("chunk_type"),
        "preview": " ".join(text.split())[:320], "length": int(row.get("char_len") or len(text)),
        "token_length": row.get("token_len"), "quality_score": row.get("quality_score"),
        "active": bool(row.get("is_active")), "created_at": _iso(row.get("created_at")), "updated_at": _iso(row.get("updated_at")),
        "quality": quality,
        "index_status": index_status,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    forbidden = {"path", "local_path", "absolute_path", "file_path", "storage_path"}
    return {key: item for key, item in value.items() if str(key).lower() not in forbidden and not str(key).lower().endswith("_path")}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


__all__ = ["DocumentAdminRepository", "DocumentContentResource"]
