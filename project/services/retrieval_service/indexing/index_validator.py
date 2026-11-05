from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import pickle
from hashlib import sha256
import numpy as np

from services.ingest_service.external_ingestion import connect_mysql
from services.retrieval_service.config import AppConfig
from services.retrieval_service.bm25_index import bm25_tokenize, load_bm25_payload

from .index_manifest import audit_old_index, build_candidate_chunk_manifest, sha256_file
from .artifact_io import read_faiss_index


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _database_valid_chunk_ids(cfg: AppConfig) -> set[int]:
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT c.id FROM chunks c JOIN documents d ON d.id=c.doc_id "
            "WHERE c.is_active=1 AND c.text IS NOT NULL AND CHAR_LENGTH(TRIM(c.text))>0 ORDER BY c.id"
        )
        return {int(row[0]) for row in (cursor.fetchall() or [])}
    finally:
        connection.close()


def validate_candidate_index(cfg: AppConfig, build: dict[str, Any]) -> dict[str, Any]:
    import faiss  # type: ignore

    faiss_path = Path(str(build["faiss_path"]))
    bm25_path = Path(str(build["bm25_path"]))
    mapping_path = Path(str(build["mapping_path"]))
    manifest_path = Path(str(build["chunk_manifest_path"]))
    faiss_meta_path = Path(str(build["faiss_meta_path"]))
    bm25_meta_path = Path(str(build["bm25_meta_path"]))
    errors: list[str] = []
    try:
        index = read_faiss_index(faiss_path)
        # The validator reports token/content differences separately below;
        # runtime loaders reject them immediately.
        bm25, tokenizer_version = load_bm25_payload(bm25_path, bm25_meta_path, expected_version=build.get("bm25_tokenizer_version"), verify_tokens=False)
        mapping = _read_json(mapping_path)
        faiss_meta = _read_json(faiss_meta_path)
        bm25_meta = _read_json(bm25_meta_path)
        manifest_rows = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        reload_success = True
    except Exception as exc:
        return {
            "passed": False,
            "reload_success": False,
            "errors": [f"reload_failed:{type(exc).__name__}:{exc}"],
        }

    faiss_count = int(index.ntotal)
    bm25_ids = [int(item) for item in bm25.get("chunk_ids", [])]
    mapping_ids = [int(item) for item in mapping.get("chunk_ids", [])]
    manifest_ids = [int(item["chunk_id"]) for item in manifest_rows]
    database_ids = _database_valid_chunk_ids(cfg)
    duplicate_count = (
        len(mapping_ids) - len(set(mapping_ids))
        + len(bm25_ids) - len(set(bm25_ids))
        + len(manifest_ids) - len(set(manifest_ids))
    )
    invalid_ids = sorted((set(mapping_ids) | set(bm25_ids) | set(manifest_ids)) - database_ids)
    missing_ids = sorted(database_ids - set(manifest_ids))
    old = audit_old_index(cfg)
    dimension_match = int(index.d) == int(old["faiss"]["dimension"])
    model_match = str(faiss_meta.get("model_name")) == str(cfg.embedding.model_name)
    normalize_match = bool(faiss_meta.get("normalize")) == bool(cfg.embedding.normalize)
    embedding_policy_match = build.get("embedding_policy") == faiss_meta.get("embedding_policy") == mapping.get("embedding_policy")
    bm25_parameter_match = (
        float(bm25_meta.get("k1")) == float(cfg.bm25.k1)
        and float(bm25_meta.get("b")) == float(cfg.bm25.b)
    )
    hash_matches = {
        "faiss": sha256_file(faiss_path) == str(build.get("hashes", {}).get("faiss")),
        "faiss_meta": sha256_file(faiss_meta_path) == str(build.get("hashes", {}).get("faiss_meta")),
        "bm25": sha256_file(bm25_path) == str(build.get("hashes", {}).get("bm25")),
        "bm25_meta": sha256_file(bm25_meta_path) == str(build.get("hashes", {}).get("bm25_meta")),
        "mapping": sha256_file(mapping_path) == str(build.get("hashes", {}).get("mapping")),
        "chunk_manifest": sha256_file(manifest_path) == str(build.get("hashes", {}).get("chunk_manifest")),
    }
    set_equal = set(mapping_ids) == set(bm25_ids) == set(manifest_ids) == database_ids
    positions_contiguous = [int(item.get("position")) for item in mapping.get("entries", [])] == list(range(len(mapping_ids)))
    mapping_order_equal = mapping_ids == bm25_ids == manifest_ids and [int(item["chunk_id"]) for item in mapping.get("entries", [])] == mapping_ids
    current_manifest = build_candidate_chunk_manifest(cfg)
    current_by_id = {int(row["chunk_id"]): row for row in current_manifest["rows"]}
    content_mismatches: list[int] = []
    provenance_mismatches: list[int] = []
    corpus_texts = bm25.get("corpus_texts") or []
    tokenized_corpus_matches = (len(corpus_texts) == len(bm25_ids)
                               and bm25.get("tokenized_corpus") == [bm25_tokenize(str(text), version=tokenizer_version) for text in corpus_texts])
    metadata_counts_match = (int(faiss_meta.get("ntotal", -1)) == faiss_count
                            and int(faiss_meta.get("dim", -1)) == int(index.d)
                            and int(bm25_meta.get("chunk_count", -1)) == len(bm25_ids))
    for position, row in enumerate(manifest_rows):
        chunk_id = int(row["chunk_id"])
        current = current_by_id.get(chunk_id) or {}
        corpus_hash = sha256(" ".join(str(corpus_texts[position]).split()).encode("utf-8")).hexdigest() if position < len(corpus_texts) else None
        if row.get("normalized_content_hash") != current.get("normalized_content_hash") or corpus_hash != current.get("normalized_content_hash"):
            content_mismatches.append(chunk_id)
        if any(row.get(key) != current.get(key) for key in ("document_id", "source_path", "page", "page_end")):
            provenance_mismatches.append(chunk_id)
    vectors = index.reconstruct_n(0, faiss_count)
    vectors_finite = bool(np.isfinite(vectors).all())
    vector_norms_valid = not cfg.embedding.normalize or bool(np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3))
    if not set_equal:
        errors.append("faiss_bm25_manifest_database_chunk_id_set_mismatch")
    if duplicate_count:
        errors.append("duplicate_indexed_chunk_ids")
    if invalid_ids:
        errors.append("invalid_chunk_mappings")
    if missing_ids:
        errors.append("missing_database_chunk_ids")
    if not positions_contiguous:
        errors.append("mapping_positions_not_contiguous")
    if not mapping_order_equal:
        errors.append("faiss_bm25_manifest_mapping_order_mismatch")
    if not tokenized_corpus_matches:
        errors.append("bm25_tokenized_corpus_differs_from_text")
    if not metadata_counts_match:
        errors.append("artifact_metadata_counts_mismatch")
    if content_mismatches:
        errors.append("candidate_content_differs_from_database")
    if provenance_mismatches:
        errors.append("candidate_provenance_differs_from_database")
    if not vectors_finite or not vector_norms_valid:
        errors.append("candidate_vectors_invalid")
    if not dimension_match:
        errors.append("embedding_dimension_changed")
    if not model_match:
        errors.append("embedding_model_changed")
    if not normalize_match:
        errors.append("embedding_normalization_changed")
    if not embedding_policy_match:
        errors.append("embedding_policy_manifest_mismatch")
    if not bm25_parameter_match:
        errors.append("bm25_parameters_changed")
    if not all(hash_matches.values()):
        errors.append("candidate_file_hash_mismatch")
    counts_equal = faiss_count == len(bm25_ids) == len(mapping_ids) == len(manifest_ids) == len(database_ids)
    if not counts_equal:
        errors.append("candidate_counts_mismatch")

    return {
        "passed": not errors,
        "candidate_version": build.get("version"),
        "candidate_hashes": dict(build.get("hashes") or {}),
        "errors": errors,
        "reload_success": reload_success,
        "faiss_count": faiss_count,
        "faiss_dimension": int(index.d),
        "bm25_count": len(bm25_ids),
        "mapping_count": len(mapping_ids),
        "manifest_count": len(manifest_ids),
        "database_valid_chunk_count": len(database_ids),
        "faiss_bm25_chunk_id_set_equal": set_equal,
        "duplicate_indexed_ids": duplicate_count,
        "invalid_chunk_mapping_count": len(invalid_ids),
        "invalid_chunk_ids": invalid_ids,
        "missing_chunk_ids": missing_ids,
        "mapping_positions_contiguous": positions_contiguous,
        "mapping_order_equal": mapping_order_equal,
        "tokenized_corpus_matches": tokenized_corpus_matches,
        "bm25_tokenizer_version": tokenizer_version,
        "metadata_counts_match": metadata_counts_match,
        "content_matches_database": not content_mismatches,
        "content_mismatch_chunk_ids": content_mismatches,
        "provenance_matches_database": not provenance_mismatches,
        "provenance_mismatch_chunk_ids": provenance_mismatches,
        "vectors_finite": vectors_finite,
        "vector_norms_valid": vector_norms_valid,
        "dimension_match_old": dimension_match,
        "embedding_model_match": model_match,
        "normalization_match": normalize_match,
        "embedding_policy_match": embedding_policy_match,
        "bm25_parameter_match": bm25_parameter_match,
        "hash_matches": hash_matches,
        "knowledge_units_included": bool(
            build.get("knowledge_units_included")
            or mapping.get("knowledge_units_included")
            or faiss_meta.get("knowledge_units_included")
            or bm25_meta.get("knowledge_units_included")
        ),
        "database_written": False,
    }
