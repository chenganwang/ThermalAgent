from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from services.ingest_service.chunking.pack import strip_packed_meta
from .config import AppConfig
from .embeddings.provider import embed_texts, get_embedder as _provider_get_embedder
from .indexing.artifact_io import read_faiss_index, write_faiss_index


def get_embedder(cfg: AppConfig):
    return _provider_get_embedder(cfg.embedding.model_name)


@dataclass
class FaissIndexManager:
    cfg: AppConfig

    def ensure_dir(self) -> None:
        self.cfg.paths.faiss_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.paths.faiss_index_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.paths.faiss_meta_path.parent.mkdir(parents=True, exist_ok=True)

    def load_or_create(self, dim: int):
        import faiss  # type: ignore

        self.ensure_dir()
        p = self.cfg.paths.faiss_index_path
        if p.exists():
            return read_faiss_index(p)
        return faiss.IndexFlatIP(int(dim))

    def save(self, index, meta: dict) -> None:
        import faiss  # type: ignore

        self.ensure_dir()
        write_faiss_index(index, self.cfg.paths.faiss_index_path)
        self.cfg.paths.faiss_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_vectors(self, vectors: np.ndarray, *, build_id: str | None = None, meta_extra: dict | None = None):
        if vectors.ndim != 2:
            raise ValueError("vectors must be 2D")
        index = self.load_or_create(int(vectors.shape[1]))
        start = index.ntotal
        index.add(vectors)
        end = index.ntotal - 1
        meta = self.read_meta()
        meta.update(
            {
                "build_id": build_id or meta.get("build_id") or str(uuid.uuid4()),
                "updated_at": int(time.time()),
                "dim": int(index.d),
                "ntotal": int(index.ntotal),
                "normalize": bool(self.cfg.embedding.normalize),
                "model_name": self.cfg.embedding.model_name,
            }
        )
        if meta_extra:
            meta.update(meta_extra)
        self.save(index, meta)
        return int(start), int(end)

    def write_meta(self, **kwargs) -> None:
        meta = self.read_meta()
        meta.update(kwargs)
        if "updated_at" not in meta:
            meta["updated_at"] = int(time.time())
        self.cfg.paths.faiss_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_meta(self) -> dict:
        p = self.cfg.paths.faiss_meta_path
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}


def build_embeddings(cfg: AppConfig, texts: Sequence[str], *, strip_meta: bool = True) -> np.ndarray:
    cleaned = [strip_packed_meta(t) if strip_meta else (t or "").strip() for t in texts]
    arr = embed_texts(cfg, cleaned, normalize=cfg.embedding.normalize)
    return np.asarray(arr, dtype="float32")


def validate_index_vs_db(cfg: AppConfig, db, *, bundle=None) -> dict:
    import faiss  # type: ignore
    from .indexing.active_bundle import resolve_active_bundle

    bundle = bundle or resolve_active_bundle(cfg)
    cfg = bundle.cfg
    fim = FaissIndexManager(cfg)
    meta = fim.read_meta()
    index_count = int(read_faiss_index(cfg.paths.faiss_index_path).ntotal)
    emb_count = int(db.fetchone("SELECT COUNT(*) FROM embeddings")[0])
    active_chunk_count = int(db.fetchone("SELECT COUNT(*) FROM chunks WHERE is_active=1")[0])
    dup_vector_rows = int(
        db.fetchone(
            "SELECT COUNT(*) FROM (SELECT vector_pos, COUNT(*) c FROM embeddings GROUP BY vector_pos HAVING c>1) t"
        )[0]
    )
    minmax = db.fetchone("SELECT MIN(vector_pos), MAX(vector_pos) FROM embeddings")
    min_pos = int(minmax[0]) if minmax and minmax[0] is not None else None
    max_pos = int(minmax[1]) if minmax and minmax[1] is not None else None
    gaps = 0
    if emb_count > 0 and min_pos is not None and max_pos is not None:
        expected = max_pos - min_pos + 1
        gaps = max(0, expected - emb_count)
    active_mapping_count = len(bundle.mapping_chunk_ids) if bundle.mapping_chunk_ids is not None else emb_count
    if bundle.mapping_chunk_ids is not None:
        dup_vector_rows = len(bundle.mapping_chunk_ids) - len(set(bundle.mapping_chunk_ids))
        min_pos, max_pos, gaps = 0, active_mapping_count - 1, 0
    return {
        "faiss_ntotal": index_count,
        "embeddings_rows": emb_count,
        "active_embedding_mapping_count": active_mapping_count,
        "mapping_source": "active_manifest" if bundle.active else "database_embeddings",
        "index_generation": bundle.version,
        "active_chunks": active_chunk_count,
        "duplicate_vector_pos_groups": dup_vector_rows,
        "vector_pos_min": min_pos,
        "vector_pos_max": max_pos,
        "vector_pos_gaps": gaps,
        "is_consistent": index_count == active_mapping_count == active_chunk_count and dup_vector_rows == 0 and gaps == 0,
        "meta": meta,
    }
