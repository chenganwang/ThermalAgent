"""Resolve one immutable FAISS/BM25/mapping generation for an entire read.

Publishing changes only the existing active-manifest pointer. Legacy files and
the legacy embeddings table remain available for rollback. Ordinary reads never
create index files or update database mappings.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any

from ..config import AppConfig
from .artifact_io import sha256_file
from ..bm25_artifact import load_bm25_payload


@dataclass(frozen=True)
class ActiveIndexBundle:
    cfg: AppConfig
    version: str
    mapping_chunk_ids: tuple[int, ...] | None = None
    pointer_sha256: str | None = None
    active: bool = False


_CACHE: dict[tuple, tuple[dict[str, Any], tuple[int, ...]]] = {}
_LOCK = RLock()
_PATH_KEYS = {
    "faiss": "faiss_path", "faiss_meta": "faiss_meta_path", "bm25": "bm25_path",
    "bm25_meta": "bm25_meta_path", "mapping": "mapping_path", "chunk_manifest": "chunk_manifest_path",
}


def active_manifest_path(cfg: AppConfig) -> Path:
    return cfg.paths.project_root / "runtime" / "index_upgrade" / "active_index_manifest.json"


def _read_manifest(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("Active index manifest exceeds its size limit")
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict) or not payload.get("active_version"):
        raise ValueError("Active index manifest is invalid")
    return payload, sha256(raw).hexdigest()


def resolve_active_bundle(cfg: AppConfig, *, pointer: Path | None = None) -> ActiveIndexBundle:
    pointer = pointer or active_manifest_path(cfg)
    if not pointer.exists():
        return ActiveIndexBundle(cfg=cfg, version="legacy_database_mapping")
    payload, pointer_hash = _read_manifest(pointer)
    hashes = payload.get("candidate_hashes") or {}
    required = dict(_PATH_KEYS)
    if payload.get("mode") == "legacy_snapshot":
        required.pop("chunk_manifest")
    paths = {key: Path(str(payload.get(name) or "")) for key, name in required.items()}
    if any(not path.is_absolute() or not path.is_file() for path in paths.values()):
        raise ValueError("Active index bundle contains a missing or non-absolute artifact path")
    signatures = tuple((key, str(path), path.stat().st_mtime_ns, path.stat().st_size) for key, path in paths.items())
    cache_key = (pointer_hash, signatures)
    with _LOCK:
        cached = _CACHE.get(cache_key)
    if cached is None:
        if any(not hashes.get(key) or sha256_file(path) != hashes[key] for key, path in paths.items()):
            raise ValueError("Active index bundle failed artifact hash validation")
        faiss_meta = json.loads(paths["faiss_meta"].read_text(encoding="utf-8"))
        bm25_meta = json.loads(paths["bm25_meta"].read_text(encoding="utf-8"))
        load_bm25_payload(paths["bm25"], paths["bm25_meta"])
        mapping = json.loads(paths["mapping"].read_text(encoding="utf-8"))
        if payload.get("mode") == "legacy_snapshot":
            entries = sorted(mapping.get("entries") or [], key=lambda item: int(item["vector_pos"]))
            if [int(item["vector_pos"]) for item in entries] != list(range(len(entries))):
                raise ValueError("Legacy snapshot mapping positions are not contiguous")
            chunk_ids = tuple(int(item["chunk_id"]) for item in entries)
        else:
            entries = mapping.get("entries") or []
            chunk_ids = tuple(int(item) for item in mapping.get("chunk_ids") or [])
            if [(int(item["position"]), int(item["chunk_id"])) for item in entries] != list(enumerate(chunk_ids)):
                raise ValueError("Active index mapping order differs from its vector positions")
        if not chunk_ids or len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Active index mapping is empty or contains duplicate chunks")
        if int(faiss_meta.get("ntotal", -1)) != len(chunk_ids) or int(bm25_meta.get("chunk_count", -1)) != len(chunk_ids):
            raise ValueError("Active index artifact counts differ")
        cached = (faiss_meta, chunk_ids)
        with _LOCK:
            # A new pointer generation invalidates the previous bundle cache.
            _CACHE.clear()
            _CACHE[cache_key] = cached
    faiss_meta, chunk_ids = cached
    if str(faiss_meta.get("model_name")) != cfg.embedding.model_name or bool(faiss_meta.get("normalize")) != cfg.embedding.normalize:
        raise ValueError("Active index embedding contract differs from the configured model")
    resolved_paths = replace(
        cfg.paths, faiss_dir=paths["faiss"].parent, faiss_index_path=paths["faiss"],
        faiss_meta_path=paths["faiss_meta"], bm25_dir=paths["bm25"].parent,
        bm25_corpus_path=paths["bm25"], bm25_meta_path=paths["bm25_meta"],
    )
    return ActiveIndexBundle(
        cfg=replace(cfg, paths=resolved_paths), version=str(payload["active_version"]),
        mapping_chunk_ids=chunk_ids, pointer_sha256=pointer_hash, active=True,
    )


__all__ = ["ActiveIndexBundle", "active_manifest_path", "resolve_active_bundle"]
