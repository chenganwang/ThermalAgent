from __future__ import annotations

import argparse
import time
import uuid
from typing import List, Tuple

from services.retrieval_service.config import load_config
from services.retrieval_service.db import DB
from services.retrieval_service.embed_index import FaissIndexManager, build_embeddings, validate_index_vs_db
from services.retrieval_service.bm25_index import rebuild_bm25_index, validate_bm25_vs_db
from .db_schema_compat import safe_upsert_embeddings_meta, safe_wipe_embeddings_rows


def _safe_unlink(p) -> None:
    try:
        if p.exists():
            p.unlink()
    except Exception as e:
        print(f"[warn] failed to delete {p}: {e}")


def wipe_faiss_files(cfg) -> None:
    _safe_unlink(cfg.paths.faiss_index_path)
    _safe_unlink(cfg.paths.faiss_meta_path)


def wipe_embeddings_rows(db: DB) -> bool:
    return safe_wipe_embeddings_rows(db)


def fetch_active_chunks(db: DB) -> List[Tuple[int, str]]:
    rows = db.list_active_chunks_for_rebuild()
    return [(int(cid), str(txt)) for (cid, txt, _ctype, _token_len) in rows]


def rebuild_all(cfg, db: DB, *, batch: int | None = None, wipe_db: bool = True, wipe_faiss: bool = True, dry_run: bool = False) -> None:
    batch = batch or cfg.rebuild.batch_size
    chunks = fetch_active_chunks(db)
    total = len(chunks)
    print(f"[step] fetch active chunks -> {total}")
    if dry_run:
        print(f"[dry-run] model={cfg.embedding.model_name} batch={batch} would_rebuild={total}")
        return

    if wipe_db:
        print("[step] wipe embeddings table ...")
        wipe_embeddings_rows(db)
    if wipe_faiss:
        print("[step] wipe FAISS files ...")
        wipe_faiss_files(cfg)
    if not chunks:
        print("[done] no active chunks found.")
        return

    fm = FaissIndexManager(cfg)
    processed = 0
    build_id = str(uuid.uuid4())
    started_at = int(time.time())
    print(f"[info] rebuilding embeddings for {total} chunks (FULL REBUILD) build_id={build_id}")
    for i in range(0, total, batch):
        batch_rows = chunks[i : i + batch]
        chunk_ids = [cid for cid, _ in batch_rows]
        texts = [t for _, t in batch_rows]
        print(f"[step] build batch embeddings {i}-{i+len(batch_rows)-1}")
        vec = build_embeddings(cfg, texts, strip_meta=True)
        start_pos, _ = fm.add_vectors(
            vec,
            build_id=build_id,
            meta_extra={
                "built_at": started_at,
                "built_from_active_only": True,
                "chunk_count": total,
                "embedding_model": cfg.embedding.model_name,
                "source_db": cfg.mysql.database,
            },
        )
        dim = int(vec.shape[1])
        print(f"[step] upsert mapping start_vpos={start_pos} batch={len(chunk_ids)}")
        items = [(chunk_ids[j], cfg.embedding.model_name, dim, int(start_pos + j)) for j in range(len(chunk_ids))]
        safe_upsert_embeddings_meta(db, items=items)
        processed += len(batch_rows)
        print(f"[progress] {processed}/{total} (last_chunk_id={chunk_ids[-1]})")

    fm.write_meta(
        build_id=build_id,
        built_at=started_at,
        built_from_active_only=True,
        chunk_count=total,
        embedding_model=cfg.embedding.model_name,
        source_db=cfg.mysql.database,
        normalize=cfg.embedding.normalize,
    )
    print('[step] rebuild BM25 index ...')
    rebuild_bm25_index(cfg, db)
    try:
        result = validate_index_vs_db(cfg, db)
        print(
            f"[verify] faiss_ntotal={result['faiss_ntotal']} embeddings_rows={result.get('embeddings_rows', 'n/a')} "
            f"active_chunks={result['active_chunks']} dup_groups={result.get('duplicate_vector_pos_groups', 'n/a')} "
            f"gaps={result.get('vector_pos_gaps', 'n/a')} consistent={result['is_consistent']}"
        )
    except Exception as exc:
        print(f"[warn] FAISS/MySQL validation skipped: {exc}")
    try:
        bm25_result = validate_bm25_vs_db(cfg, db)
        print(
            f"[verify-bm25] bm25_chunk_count={bm25_result['bm25_chunk_count']} "
            f"db_chunks={bm25_result['db_active_chunks_for_bm25']} consistent={bm25_result['is_consistent']}"
        )
    except Exception as exc:
        print(f"[warn] BM25 validation skipped: {exc}")
    print("[done] rebuild finished.")


def main():
    ap = argparse.ArgumentParser(description="Rebuild FAISS index + embeddings mapping from chunks(text)")
    ap.add_argument("--batch", type=int, default=None, help="Embedding batch size")
    ap.add_argument("--full", action="store_true", help="Full rebuild: wipe embeddings + wipe faiss (recommended)")
    ap.add_argument("--wipe-db", action="store_true", help="Wipe MySQL embeddings mapping first")
    ap.add_argument("--wipe-faiss", action="store_true", help="Delete FAISS index/meta files first")
    ap.add_argument("--dry-run", action="store_true", help="Only inspect rebuild scope; do not write DB or FAISS")
    args = ap.parse_args()

    cfg = load_config()
    db = DB.create(cfg)
    if args.dry_run:
        rebuild_all(cfg, db, batch=args.batch, wipe_db=False, wipe_faiss=False, dry_run=True)
        return
    if args.full or (not args.wipe_db and not args.wipe_faiss):
        rebuild_all(cfg, db, batch=args.batch, wipe_db=True, wipe_faiss=True)
        return
    rebuild_all(cfg, db, batch=args.batch, wipe_db=args.wipe_db, wipe_faiss=args.wipe_faiss)


if __name__ == "__main__":
    main()
