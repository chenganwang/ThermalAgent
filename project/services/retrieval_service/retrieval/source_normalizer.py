from __future__ import annotations

from typing import Any

from ..schemas import RetrievedChunk
from .retrieval_types import RetrievalHitSnapshot, snapshot_hit


def hit_to_snapshot(hit: Any) -> RetrievalHitSnapshot:
    """Normalize a Hit-like object to a serializable retrieval snapshot."""

    return snapshot_hit(hit)


def hit_to_retrieved_chunk(hit: Any) -> RetrievedChunk:
    """Normalize a retriever Hit-like object to a stable internal chunk."""

    snapshot = hit_to_snapshot(hit)
    return RetrievedChunk(
        score=snapshot.score,
        vector_score=snapshot.vector_score,
        bm25_score=snapshot.bm25_score,
        lexical_score=snapshot.lexical_score,
        doc_id=snapshot.doc_id,
        chunk_id=snapshot.chunk_id,
        chunk_index=snapshot.chunk_index,
        page_start=snapshot.page_start,
        page_end=snapshot.page_end,
        chunk_type=snapshot.chunk_type,
        text=snapshot.text,
        expanded_text=snapshot.expanded_text,
        section_path=snapshot.section_path,
        neighbors=snapshot.neighbors,
        retrieval_routes=snapshot.retrieval_routes,
        exact_reference_matches=snapshot.exact_reference_matches,
        meta_json=snapshot.meta_json,
    )


def normalize_hits(hits: list[Any]) -> list[RetrievedChunk]:
    return [hit_to_retrieved_chunk(hit) for hit in hits]
