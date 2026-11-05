from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Protocol
from uuid import uuid4

from ..contracts import AdminAPIError


_CANDIDATE_ID = re.compile(r"^indexcand-[a-f0-9]{32}$")


class KnowledgeIndexAdapter(Protocol):
    def current_content_digest(self) -> str: ...
    def build_candidate(self, *, content_revision_digest: str) -> dict[str, Any]: ...
    def validate_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]: ...
    def release_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]: ...


class KnowledgeIndexStateStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._lock = RLock()

    def save(self, value: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(value)
        candidate_id = self._id(str(payload.get("candidate_id") or ""))
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{candidate_id}.json"
        temporary = path.with_suffix(".json.tmp")
        with self._lock:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        return payload

    def get(self, candidate_id: str) -> dict[str, Any]:
        normalized = self._id(candidate_id)
        path = self.root / f"{normalized}.json"
        if not path.is_file():
            raise AdminAPIError("INDEX_CANDIDATE_NOT_FOUND", "Index candidate was not found.", status_code=404)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise AdminAPIError("INDEX_CANDIDATE_CORRUPT", "Index candidate state is unreadable.", status_code=500) from exc
        if not isinstance(value, dict):
            raise AdminAPIError("INDEX_CANDIDATE_CORRUPT", "Index candidate state is invalid.", status_code=500)
        return value

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        values = []
        for path in self.root.glob("indexcand-*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict):
                values.append(value)
        return sorted(values, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    @staticmethod
    def _id(value: str) -> str:
        if not _CANDIDATE_ID.fullmatch(str(value or "")):
            raise AdminAPIError("INDEX_CANDIDATE_ID_INVALID", "Invalid index candidate identifier.", status_code=422)
        return value


class KnowledgeIndexSyncService:
    def __init__(self, store: KnowledgeIndexStateStore, adapter: KnowledgeIndexAdapter) -> None:
        self.store = store
        self.adapter = adapter
        self._lock = RLock()

    def build_candidate(self, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            digest = str(self.adapter.current_content_digest())
            existing = next(
                (
                    item for item in self.store.list()
                    if str(item.get("content_revision_digest") or "") == digest
                    and item.get("status") in {"candidate_ready", "ready_to_release", "release_failed", "synced"}
                ),
                None,
            )
            if existing is not None:
                return {**_public(existing), "idempotent": True}
            candidate_id = f"indexcand-{uuid4().hex}"
            now = _now()
            payload = {
                "candidate_id": candidate_id,
                "status": "building",
                "content_revision_digest": digest,
                "created_at": now,
                "updated_at": now,
                "actor_id": str(actor_id or "admin")[:200],
                "active_index_modified": False,
                "idempotent": False,
            }
            self.store.save(payload)
            try:
                build = dict(self.adapter.build_candidate(content_revision_digest=digest))
            except Exception as exc:
                payload.update({"status": "validation_failed", "error_code": "INDEX_CANDIDATE_BUILD_FAILED", "error_type": type(exc).__name__, "updated_at": _now()})
                self.store.save(payload)
                raise AdminAPIError("INDEX_CANDIDATE_BUILD_FAILED", "Index candidate build failed.", status_code=500) from exc
            vector_ready = bool(build.get("faiss_built"))
            lexical_ready = bool(build.get("bm25_built"))
            payload.update({
                "status": "candidate_ready" if vector_ready and lexical_ready else "validation_failed",
                "version": build.get("version"),
                "build": build,
                "faiss_ready": vector_ready,
                "bm25_ready": lexical_ready,
                "active_index_modified": bool(build.get("active_index_modified", False)),
                "updated_at": _now(),
            })
            if payload["active_index_modified"]:
                payload.update({"status": "validation_failed", "error_code": "ACTIVE_INDEX_MODIFIED_DURING_BUILD"})
            self.store.save(payload)
            return _public(payload)

    def validate_candidate(self, candidate_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self.store.get(candidate_id)
            if payload.get("status") == "ready_to_release":
                return _public(payload)
            self._require_digest_match(payload)
            validation = dict(self.adapter.validate_candidate(dict(payload.get("build") or {})))
            vector_ready = bool(validation.get("faiss_ready"))
            lexical_ready = bool(validation.get("bm25_ready"))
            if bool(validation.get("passed")) and vector_ready and lexical_ready and bool(validation.get("retrieval_smoke_passed")):
                status = "ready_to_release"
            elif vector_ready and lexical_ready:
                status = "candidate_ready"
            else:
                status = "validation_failed"
            payload.update({
                "status": status,
                "validation": validation,
                "validated_by": str(actor_id or "admin")[:200],
                "updated_at": _now(),
            })
            self.store.save(payload)
            return _public(payload)

    def release_candidate(self, candidate_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self.store.get(candidate_id)
            if payload.get("status") in {"synced", "release_failed"}:
                return {**_public(payload), "idempotent": True}
            if payload.get("status") != "ready_to_release":
                raise AdminAPIError("INDEX_CANDIDATE_NOT_RELEASE_READY", "Index candidate is not ready to release.", status_code=409)
            self._require_digest_match(payload)
            release = dict(self.adapter.release_candidate(dict(payload.get("build") or {})))
            synchronized = bool(release.get("released")) and bool(release.get("live_retrieval_switched"))
            payload.update({
                "status": "synced" if synchronized else "release_failed",
                "release": release,
                "released_by": str(actor_id or "admin")[:200],
                "updated_at": _now(),
            })
            if not synchronized:
                payload["error_code"] = str(release.get("error_code") or "INDEX_RELEASE_NOT_ACTIVE")
            self.store.save(payload)
            return {**_public(payload), "idempotent": False}

    def status(self) -> dict[str, Any]:
        items = self.store.list()
        return {"status": str(items[0].get("status") or "synced") if items else "synced", "candidates": [_public(item) for item in items]}

    def _require_digest_match(self, payload: Mapping[str, Any]) -> None:
        current = str(self.adapter.current_content_digest())
        expected = str(payload.get("content_revision_digest") or "")
        if not expected or current != expected:
            mutable = dict(payload)
            mutable.update({"status": "validation_failed", "error_code": "INDEX_CONTENT_REVISION_MISMATCH", "updated_at": _now()})
            self.store.save(mutable)
            raise AdminAPIError("INDEX_CONTENT_REVISION_MISMATCH", "Knowledge content changed after the candidate was built.", status_code=409)


def _public(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "candidate_id", "status", "version", "content_revision_digest", "faiss_ready", "bm25_ready",
        "active_index_modified", "validation", "release", "error_code", "created_at", "updated_at",
        "idempotent",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["KnowledgeIndexAdapter", "KnowledgeIndexStateStore", "KnowledgeIndexSyncService"]
