from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import json
import os
import pickle

import numpy as np

from services.ingest_service.chunking.pack import strip_packed_meta
from services.retrieval_service.bm25_index import bm25_tokenize, CURRENT_TOKENIZER_VERSION
from services.retrieval_service.config import AppConfig
from services.retrieval_service.embed_index import build_embeddings
from .artifact_io import write_faiss_index

from .index_manifest import (
    audit_old_index,
    build_candidate_chunk_manifest,
    sha256_file,
)


def utc_candidate_version() -> str:
    return "v_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def plan_candidate_build(
    cfg: AppConfig,
    output_root: str | Path,
    *,
    version: str | None = None,
) -> dict[str, Any]:
    old = audit_old_index(cfg)
    manifest = build_candidate_chunk_manifest(cfg)
    active_version = version or utc_candidate_version()
    return {
        "status": "dry_run",
        "version": active_version,
        "version_dir": str((Path(output_root) / active_version).resolve()),
        "chunk_count": manifest["summary"]["manifest_count"],
        "database_valid_chunk_count": manifest["summary"]["database_valid_chunk_count"],
        "embedding_model": cfg.embedding.model_name,
        "embedding_dimension": old["faiss"]["dimension"],
        "normalize": cfg.embedding.normalize,
        "faiss_metric": "inner_product" if old["faiss"]["metric_type"] == 0 else str(old["faiss"]["metric_type"]),
        "faiss_index_class": old["faiss"]["index_class"],
        "bm25_k1": cfg.bm25.k1,
        "bm25_b": cfg.bm25.b,
        "bm25_enabled": cfg.bm25.enabled,
        "bm25_tokenizer_version": CURRENT_TOKENIZER_VERSION,
        "knowledge_units_included": False,
        "database_write_planned": False,
        "production_files_modified": False,
        "external_download_allowed": False,
        "production_hashes_before": {
            "faiss": old["faiss"]["sha256"],
            "faiss_meta": old["faiss"]["meta_sha256"],
            "bm25": old["bm25"]["sha256"],
            "bm25_meta": old["bm25"]["meta_sha256"],
        },
    }


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


def _atomic_pickle(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(payload, handle)
    os.replace(temporary, path)


def build_candidate_indexes(
    cfg: AppConfig,
    output_root: str | Path,
    *,
    version: str | None = None,
    batch_size: int | None = None,
    embed_batch: Callable[[list[str]], np.ndarray] | None = None,
    embedding_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import faiss  # type: ignore

    plan = plan_candidate_build(cfg, output_root, version=version)
    version_dir = Path(plan["version_dir"])
    try:
        version_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError("candidate versions are immutable; choose a new version") from exc
    policy = dict(embedding_policy or {"schema_version": "1.0", "document_strategy": "model_default_single", "query_strategy": "model_default_single"})
    faiss_dir = version_dir / "faiss"
    bm25_dir = version_dir / "bm25"
    faiss_dir.mkdir(parents=True, exist_ok=True)
    bm25_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_candidate_chunk_manifest(cfg)
    rows = manifest["rows"]
    texts = [strip_packed_meta(str(row.get("text") or "")) for row in rows]

    tokenized = [bm25_tokenize(text) for text in texts]
    bm25_empty_positions = [index for index, tokens in enumerate(tokenized) if not tokens]
    if bm25_empty_positions:
        return {
            **plan,
            "status": "blocked",
            "blocking_reason": "bm25_tokenizer_produced_empty_entries",
            "bm25_empty_positions": bm25_empty_positions,
        }

    dimension = int(plan["embedding_dimension"])
    index = faiss.IndexFlatIP(dimension)
    batch = int(batch_size or cfg.rebuild.batch_size)
    embedding_function = embed_batch or (
        lambda items: build_embeddings(cfg, items, strip_meta=False)
    )
    for start in range(0, len(texts), batch):
        vectors = np.asarray(embedding_function(texts[start : start + batch]), dtype="float32")
        if vectors.ndim != 2 or vectors.shape[0] != len(texts[start : start + batch]):
            raise ValueError("embedding batch shape does not match candidate manifest")
        if int(vectors.shape[1]) != dimension:
            raise ValueError(f"embedding dimension changed: expected {dimension}, got {vectors.shape[1]}")
        index.add(vectors)

    faiss_path = faiss_dir / "faiss.index"
    faiss_tmp = faiss_path.with_suffix(".index.tmp")
    write_faiss_index(index, faiss_tmp)
    os.replace(faiss_tmp, faiss_path)
    chunk_ids = [int(row["chunk_id"]) for row in rows]
    mapping_path = version_dir / "chunk_mapping.json"
    _atomic_json(
        mapping_path,
        {
            "version": plan["version"],
            "mapping_kind": "faiss_position_to_chunk_id",
            "count": len(chunk_ids),
            "chunk_ids": chunk_ids,
            "entries": [
                {"position": position, "chunk_id": chunk_id}
                for position, chunk_id in enumerate(chunk_ids)
            ],
            "knowledge_units_included": False,
            "embedding_policy": policy,
        },
    )
    faiss_meta_path = faiss_dir / "faiss.index.meta.json"
    _atomic_json(
        faiss_meta_path,
        {
            "build_id": plan["version"],
            "dim": dimension,
            "ntotal": int(index.ntotal),
            "normalize": bool(cfg.embedding.normalize),
            "model_name": cfg.embedding.model_name,
            "embedding_policy": policy,
            "metric_type": "inner_product",
            "chunk_count": len(chunk_ids),
            "built_from_database_readonly": True,
            "knowledge_units_included": False,
        },
    )

    bm25_path = bm25_dir / "bm25.pkl"
    _atomic_pickle(
        bm25_path,
        {
            "tokenizer_version": CURRENT_TOKENIZER_VERSION,
            "chunk_ids": chunk_ids,
            "tokenized_corpus": tokenized,
            "corpus_texts": texts,
        },
    )
    bm25_meta_path = bm25_dir / "bm25.pkl.meta.json"
    _atomic_json(
        bm25_meta_path,
        {
            "model_name": "bm25",
            "tokenizer_version": CURRENT_TOKENIZER_VERSION,
            "chunk_count": len(chunk_ids),
            "enabled": bool(cfg.bm25.enabled),
            "k1": cfg.bm25.k1,
            "b": cfg.bm25.b,
            "knowledge_units_included": False,
        },
    )

    manifest_path = version_dir / "candidate_chunk_manifest.jsonl"
    manifest_tmp = manifest_path.with_suffix(".jsonl.tmp")
    with manifest_tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            public_row = {key: value for key, value in row.items() if key != "text"}
            public_row["embedding_status"] = "embedded"
            handle.write(json.dumps(public_row, ensure_ascii=False, default=str) + "\n")
    os.replace(manifest_tmp, manifest_path)

    build_manifest = {
        **plan,
        "status": "built",
        "embedding_policy": policy,
        "faiss_path": str(faiss_path.resolve()),
        "faiss_meta_path": str(faiss_meta_path.resolve()),
        "bm25_path": str(bm25_path.resolve()),
        "bm25_meta_path": str(bm25_meta_path.resolve()),
        "mapping_path": str(mapping_path.resolve()),
        "chunk_manifest_path": str(manifest_path.resolve()),
        "faiss_count": int(index.ntotal),
        "bm25_count": len(chunk_ids),
        "manifest_count": len(rows),
        "hashes": {
            "faiss": sha256_file(faiss_path),
            "faiss_meta": sha256_file(faiss_meta_path),
            "bm25": sha256_file(bm25_path),
            "bm25_meta": sha256_file(bm25_meta_path),
            "mapping": sha256_file(mapping_path),
            "chunk_manifest": sha256_file(manifest_path),
        },
        "database_written": False,
        "production_files_modified": False,
        "knowledge_units_included": False,
    }
    build_manifest_path = version_dir / "build_manifest.json"
    _atomic_json(build_manifest_path, build_manifest)
    build_manifest["build_manifest_path"] = str(build_manifest_path.resolve())
    return build_manifest
