"""Construct explicit evaluation bundle descriptions without runtime stores."""
from pathlib import Path
from typing import Any
import json

from ..config import AppConfig
from .index_manifest import audit_old_index


def build_old_bundle(cfg: AppConfig) -> dict[str, Any]:
    audit = audit_old_index(cfg)
    entries = sorted(audit["old_mapping"]["entries"], key=lambda item: int(item["vector_pos"]))
    return {
        "name": "old_production",
        "version": audit["index_version"],
        "faiss_path": audit["faiss"]["path"],
        "bm25_path": audit["bm25"]["path"],
        "bm25_meta_path": audit["bm25"]["meta_path"],
        "bm25_tokenizer_version": audit["bm25"]["tokenizer_version"],
        "mapping_chunk_ids": [int(item["chunk_id"]) for item in entries],
        "knowledge_units_included": False,
    }


def build_candidate_bundle(build: dict[str, Any]) -> dict[str, Any]:
    mapping = json.loads(Path(str(build["mapping_path"])).read_text(encoding="utf-8"))
    return {
        "name": "candidate",
        "version": build.get("version"),
        "faiss_path": build["faiss_path"],
        "bm25_path": build["bm25_path"],
        "bm25_meta_path": build.get("bm25_meta_path"),
        "bm25_tokenizer_version": build.get("bm25_tokenizer_version"),
        "mapping_chunk_ids": [int(item) for item in mapping.get("chunk_ids", [])],
        "knowledge_units_included": bool(
            build.get("knowledge_units_included") or mapping.get("knowledge_units_included")
        ),
    }

