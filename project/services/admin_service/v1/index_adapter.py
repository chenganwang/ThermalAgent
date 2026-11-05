from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from services.retrieval_service.config import AppConfig
from services.retrieval_service.indexing.candidate_builder import build_candidate_indexes
from services.retrieval_service.indexing.index_manifest import build_candidate_chunk_manifest
from services.retrieval_service.indexing.index_validator import validate_candidate_index


class CanonicalKnowledgeIndexAdapter:
    """Admin adapter over the existing copy-on-write retrieval index pipeline.

    Candidate construction and integrity validation are supported. The current
    production retriever does not consume the activation pointer emitted by the
    offline release tooling, so this adapter deliberately refuses to report a
    live release until that production integration seam exists.
    """

    def __init__(self, cfg: AppConfig, candidate_root: Path) -> None:
        self.cfg = cfg
        self.candidate_root = Path(candidate_root).resolve()

    def current_content_digest(self) -> str:
        return manifest_content_digest(build_candidate_chunk_manifest(self.cfg))

    def build_candidate(self, *, content_revision_digest: str) -> dict[str, Any]:
        build = dict(build_candidate_indexes(self.cfg, self.candidate_root))
        built = str(build.get("status") or "") == "built"
        return {
            **build,
            "content_revision_digest": str(content_revision_digest),
            "faiss_built": built and bool(build.get("faiss_path")),
            "bm25_built": built and bool(build.get("bm25_path")),
            "active_index_modified": bool(build.get("production_files_modified", False)),
        }

    def validate_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        validation = dict(validate_candidate_index(self.cfg, candidate))
        passed = bool(validation.get("passed"))
        reload_passed = bool(validation.get("reload_success"))
        return {
            **validation,
            "faiss_ready": passed and int(validation.get("faiss_count") or 0) > 0,
            "bm25_ready": passed and int(validation.get("bm25_count") or 0) > 0,
            "retrieval_smoke_passed": passed and reload_passed,
            "retrieval_smoke_mode": "candidate_reload_and_mapping_integrity",
        }

    def release_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "released": False,
            "live_retrieval_switched": False,
            "active_index_modified": False,
            "candidate_version": candidate.get("version"),
            "error_code": "INDEX_RELEASE_GATE_EVIDENCE_REQUIRED",
            "capability": "requires_offline_holdout_gate_and_live_retriever_switch",
        }


def manifest_content_digest(manifest: dict[str, Any]) -> str:
    rows = []
    for raw in manifest.get("rows") or []:
        row = dict(raw)
        rows.append({
            "chunk_id": int(row.get("chunk_id") or 0),
            "document_id": int(row.get("document_id") or 0),
            "page": row.get("page"),
            "page_end": row.get("page_end"),
            "content_hash": str(row.get("content_hash") or ""),
            "normalized_content_hash": str(row.get("normalized_content_hash") or ""),
        })
    rows.sort(key=lambda item: item["chunk_id"])
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = ["CanonicalKnowledgeIndexAdapter", "manifest_content_digest"]
