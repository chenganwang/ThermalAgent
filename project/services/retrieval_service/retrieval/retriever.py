"""Retrieval package facade for the legacy root retriever module.

The core FAISS/BM25/fusion/rerank/neighbor-context implementation remains in
``services.retrieval_service.retriever`` for this conservative refactor round.
"""

from __future__ import annotations

from ..retriever import (
    Hit,
    format_hits,
    rerank_candidates,
    retrieve,
    retrieve_bm25_candidates,
    retrieve_exact_reference_candidates,
    retrieve_vector_candidates,
    retrieve_with_plan,
    warmup_retrieval_runtime,
)

__all__ = [
    "Hit",
    "format_hits",
    "rerank_candidates",
    "retrieve",
    "retrieve_bm25_candidates",
    "retrieve_exact_reference_candidates",
    "retrieve_vector_candidates",
    "retrieve_with_plan",
    "warmup_retrieval_runtime",
]
