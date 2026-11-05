"""Retrieval package facade for the legacy root RAG chain module."""

from __future__ import annotations

from ..rag_chain import (
    build_context_view,
    generate_answer,
    hits_to_sources,
    query,
    render_answer_view,
    retrieve_only,
    retrieve_only_with_plan,
    source_from_hit,
)

__all__ = [
    "build_context_view",
    "generate_answer",
    "hits_to_sources",
    "query",
    "render_answer_view",
    "retrieve_only",
    "retrieve_only_with_plan",
    "source_from_hit",
]
