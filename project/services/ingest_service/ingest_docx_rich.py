from __future__ import annotations

from pathlib import Path
import hashlib

from services.retrieval_service.config import AppConfig
from services.retrieval_service.db import DB
from .rebuild_embeddings import rebuild_all
from .db_schema_compat import (
    count_chunks_for_doc_compat,
    delete_chunks_for_doc_compat,
    get_or_create_document_compat,
    insert_chunks_compat,
    sync_document_sections_for_doc,
)

from .parsers.docx_parser import parse_docx_to_blocks
from .chunking import build_chunk_context, chunk_blocks_to_rows

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def ingest_docx(docx_path: Path, cfg: AppConfig, overwrite: bool = False) -> int:
    db = DB.create(cfg)
    sha = sha256_file(docx_path)
    title = docx_path.stem
    doc_id = get_or_create_document_compat(
        db,
        source=str(docx_path),
        title=title,
        sha256=sha,
        mime=DOCX_MIME,
        local_path=str(docx_path),
        meta_json={"ingest_service": "ingest_docx_rich"},
    )

    if not overwrite:
        if count_chunks_for_doc_compat(db, doc_id) > 0:
            return doc_id
    else:
        delete_chunks_for_doc_compat(db, doc_id)

    blocks = parse_docx_to_blocks(docx_path)
    rows = chunk_blocks_to_rows(blocks, ctx=build_chunk_context(cfg))
    insert_chunks_compat(db, doc_id=doc_id, rows=rows)
    sync_document_sections_for_doc(db, doc_id=doc_id)
    rebuild_all(cfg, db, batch=cfg.rebuild.batch_size, wipe_db=True, wipe_faiss=True)
    return doc_id
