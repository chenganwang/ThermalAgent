from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import pickle
import shutil

from services.ingest_service.external_ingestion import connect_mysql
from services.ingest_service.chunking.pack import strip_packed_meta
from services.retrieval_service.config import AppConfig
from services.retrieval_service.bm25_index import load_bm25_payload


from .artifact_io import sha256_file, read_faiss_index


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "sha256": sha256_file(path) if path.exists() else None,
        "modified_time": path.stat().st_mtime if path.exists() else None,
    }


def _database_index_snapshot(cfg: AppConfig) -> dict[str, Any]:
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) AS n FROM chunks c JOIN documents d ON d.id=c.doc_id "
            "WHERE c.is_active=1 AND c.text IS NOT NULL AND CHAR_LENGTH(TRIM(c.text))>0"
        )
        valid_chunk_count = int((cursor.fetchone() or {}).get("n") or 0)
        cursor.execute("SELECT COUNT(*) AS n FROM chunks WHERE is_active=1")
        active_chunk_count = int((cursor.fetchone() or {}).get("n") or 0)
        cursor.execute(
            "SELECT chunk_id, vector_pos, model_name, embedding_model, dim, index_name, index_version, build_id "
            "FROM embeddings ORDER BY vector_pos"
        )
        mappings = [dict(row) for row in (cursor.fetchall() or [])]
        chunk_ids = [int(item["chunk_id"]) for item in mappings]
        positions = [int(item["vector_pos"]) for item in mappings]
        return {
            "valid_chunk_count": valid_chunk_count,
            "active_chunk_count": active_chunk_count,
            "embedding_mapping_count": len(mappings),
            "mappings": mappings,
            "duplicate_chunk_ids": len(chunk_ids) - len(set(chunk_ids)),
            "duplicate_vector_positions": len(positions) - len(set(positions)),
            "vector_position_min": min(positions) if positions else None,
            "vector_position_max": max(positions) if positions else None,
            "vector_position_gaps": (
                max(positions) - min(positions) + 1 - len(set(positions)) if positions else 0
            ),
        }
    finally:
        connection.close()


def audit_old_index(cfg: AppConfig) -> dict[str, Any]:
    import faiss  # type: ignore

    faiss_path = cfg.paths.faiss_index_path
    bm25_path = cfg.paths.bm25_corpus_path
    faiss_meta = _json_file(cfg.paths.faiss_meta_path)
    bm25_meta = _json_file(cfg.paths.bm25_meta_path)
    if not faiss_path.exists() or not bm25_path.exists():
        missing = [str(path) for path in (faiss_path, bm25_path) if not path.exists()]
        raise FileNotFoundError(f"production index files missing: {missing}")

    index = read_faiss_index(faiss_path)
    payload, tokenizer_version = load_bm25_payload(bm25_path, cfg.paths.bm25_meta_path)
    bm25_ids = [int(item) for item in payload.get("chunk_ids", [])]
    tokenized = list(payload.get("tokenized_corpus", []))
    corpus_texts = list(payload.get("corpus_texts", []))
    database = _database_index_snapshot(cfg)
    mappings = database.pop("mappings")
    mapped_ids = [int(item["chunk_id"]) for item in mappings]
    mapped_positions = [int(item["vector_pos"]) for item in mappings]
    faiss_ntotal = int(index.ntotal)
    missing_mapping = max(0, faiss_ntotal - len(set(mapped_positions)))
    version = str(faiss_meta.get("build_id") or f"legacy_{sha256_file(faiss_path)[:12]}")

    return {
        "status": "ok",
        "index_version": version,
        "faiss": {
            **_file_record(faiss_path),
            "meta_path": str(cfg.paths.faiss_meta_path.resolve()),
            "meta_sha256": sha256_file(cfg.paths.faiss_meta_path),
            "ntotal": faiss_ntotal,
            "dimension": int(index.d),
            "metric_type": int(index.metric_type),
            "index_class": type(index).__name__,
            "model_name": faiss_meta.get("model_name") or faiss_meta.get("embedding_model"),
            "normalize": bool(faiss_meta.get("normalize")),
            "build_timestamp": faiss_meta.get("built_at") or faiss_meta.get("updated_at"),
            "meta": faiss_meta,
        },
        "bm25": {
            "tokenizer_version": tokenizer_version,
            **_file_record(bm25_path),
            "meta_path": str(cfg.paths.bm25_meta_path.resolve()),
            "meta_sha256": sha256_file(cfg.paths.bm25_meta_path),
            "corpus_count": len(bm25_ids),
            "tokenized_corpus_count": len(tokenized),
            "corpus_text_count": len(corpus_texts),
            "duplicate_chunk_ids": len(bm25_ids) - len(set(bm25_ids)),
            "k1": bm25_meta.get("k1"),
            "b": bm25_meta.get("b"),
            "meta": bm25_meta,
        },
        "old_mapping": {
            "count": len(mappings),
            "chunk_ids": mapped_ids,
            "vector_positions": mapped_positions,
            "duplicate_chunk_ids": len(mapped_ids) - len(set(mapped_ids)),
            "duplicate_vector_positions": len(mapped_positions) - len(set(mapped_positions)),
            "missing_mapping_entries": missing_mapping,
            "entries": mappings,
        },
        "database": database,
        "database_index_count_difference": int(database["valid_chunk_count"]) - faiss_ntotal,
        "faiss_bm25_chunk_id_set_equal": set(mapped_ids) == set(bm25_ids),
        "production_paths": {
            "faiss": str(faiss_path.resolve()),
            "faiss_meta": str(cfg.paths.faiss_meta_path.resolve()),
            "bm25": str(bm25_path.resolve()),
            "bm25_meta": str(cfg.paths.bm25_meta_path.resolve()),
        },
        "knowledge_units_included": False,
        "database_written": False,
    }


def snapshot_old_index(
    cfg: AppConfig,
    output_dir: str | Path,
    *,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = audit or audit_old_index(cfg)
    version = str(current.get("index_version") or "legacy")
    snapshot_dir = Path(output_dir) / f"old_{version}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    source_files = [
        cfg.paths.faiss_index_path,
        cfg.paths.faiss_meta_path,
        cfg.paths.bm25_corpus_path,
        cfg.paths.bm25_meta_path,
    ]
    files: list[dict[str, Any]] = []
    for source in source_files:
        target = snapshot_dir / source.name
        if not target.exists() or sha256_file(target) != sha256_file(source):
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(source, temporary)
            temporary.replace(target)
        files.append(
            {
                "source_path": str(source.resolve()),
                "snapshot_path": str(target.resolve()),
                "source_sha256": sha256_file(source),
                "snapshot_sha256": sha256_file(target),
                "size_bytes": source.stat().st_size,
            }
        )

    mapping_path = snapshot_dir / "chunk_mapping.json"
    mapping_payload = {
        "index_version": version,
        "mapping_source": "database_embeddings_readonly_export",
        "entries": current.get("old_mapping", {}).get("entries", []),
    }
    mapping_path.write_text(json.dumps(mapping_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    verified = all(item["source_sha256"] == item["snapshot_sha256"] for item in files)
    return {
        "index_version": version,
        "snapshot_dir": str(snapshot_dir.resolve()),
        "files": files,
        "mapping_path": str(mapping_path.resolve()),
        "mapping_sha256": sha256_file(mapping_path),
        "snapshot_verified": verified,
        "rollback_available": verified,
        "old_files_deleted": False,
        "database_copied": False,
        "rollback_instruction": "Restore the four versioned files and the exported vector-position mapping through the controlled rollback command.",
    }


def _normalized_content(text: str) -> str:
    return " ".join(strip_packed_meta(text or "").split())


def build_candidate_chunk_manifest(cfg: AppConfig) -> dict[str, Any]:
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                c.id AS chunk_id,
                c.doc_id AS document_id,
                c.page_start,
                c.page_end,
                c.section_path,
                c.text,
                c.content_hash AS stored_content_hash,
                d.title AS document_title,
                d.source AS source_path,
                d.local_path,
                d.sha256 AS document_sha256,
                sa.id AS source_asset_id
            FROM chunks c
            JOIN documents d ON d.id=c.doc_id
            LEFT JOIN (
                SELECT doc_id, MIN(id) AS id
                FROM source_assets
                GROUP BY doc_id
            ) first_asset ON first_asset.doc_id=d.id
            LEFT JOIN source_assets sa ON sa.id=first_asset.id
            WHERE c.is_active=1
              AND c.text IS NOT NULL
              AND CHAR_LENGTH(TRIM(c.text))>0
            ORDER BY c.id ASC
            """
        )
        raw_rows = [dict(row) for row in (cursor.fetchall() or [])]
        cursor.execute("SELECT COUNT(*) AS n FROM chunks WHERE is_active=1")
        active_count = int((cursor.fetchone() or {}).get("n") or 0)
        cursor.execute(
            "SELECT COUNT(*) AS n FROM chunks c LEFT JOIN documents d ON d.id=c.doc_id "
            "WHERE c.is_active=1 AND d.id IS NULL"
        )
        orphan_count = int((cursor.fetchone() or {}).get("n") or 0)
    finally:
        connection.close()

    rows: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_rows):
        text = str(raw.get("text") or "")
        normalized = _normalized_content(text)
        source_path = str(raw.get("source_path") or raw.get("local_path") or "")
        source_filename = Path(source_path).name if source_path else str(raw.get("document_title") or "")
        content_hash = str(raw.get("stored_content_hash") or "").strip() or sha256(text.encode("utf-8")).hexdigest()
        provenance_ready = bool(raw.get("document_id") and raw.get("document_title") and source_path)
        rows.append(
            {
                "manifest_position": position,
                "chunk_id": int(raw["chunk_id"]),
                "document_id": int(raw["document_id"]),
                "source_asset_id": int(raw["source_asset_id"]) if raw.get("source_asset_id") is not None else None,
                "document_title": raw.get("document_title"),
                "source_filename": source_filename,
                "source_path": source_path,
                "page": raw.get("page_start"),
                "page_end": raw.get("page_end"),
                "section": raw.get("section_path"),
                "content_hash": content_hash,
                "normalized_content_hash": sha256(normalized.encode("utf-8")).hexdigest(),
                "content_length": len(text),
                "embedding_status": "pending",
                "faiss_position": position,
                "bm25_position": position,
                "provenance_ready": provenance_ready,
                "text": text,
            }
        )

    ids = [row["chunk_id"] for row in rows]
    empty_count = sum(not str(row.get("text") or "").strip() for row in rows)
    provenance_count = sum(bool(row.get("provenance_ready")) for row in rows)
    return {
        "rows": rows,
        "summary": {
            "database_valid_chunk_count": len(raw_rows),
            "database_active_chunk_count": active_count,
            "manifest_count": len(rows),
            "empty_content_count": empty_count,
            "orphan_chunk_count": orphan_count,
            "duplicate_chunk_id_count": len(ids) - len(set(ids)),
            "manifest_position_contiguous": [row["manifest_position"] for row in rows] == list(range(len(rows))),
            "provenance_ready_count": provenance_count,
            "provenance_ready_rate": round(provenance_count / len(rows), 4) if rows else 0.0,
            "knowledge_units_included": False,
            "database_written": False,
        },
    }
