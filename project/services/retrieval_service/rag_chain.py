from __future__ import annotations

from typing import List

from .answering.answer_generator import generate_answer
from .answering.source_formatter import hits_to_sources, source_from_hit
from .config import AppConfig
from .query_types import QueryPlan
from .retriever import Hit, format_hits, retrieve, retrieve_with_plan


def retrieve_only(cfg: AppConfig, question: str, topk: int | None = None, neighbor_window: int | None = None) -> tuple[list[Hit], int]:
    return retrieve(cfg, question, topk=topk, neighbor_window=neighbor_window)


def retrieve_only_with_plan(
    cfg: AppConfig,
    question: str,
    topk: int | None = None,
    neighbor_window: int | None = None,
) -> tuple[list[Hit], int, QueryPlan]:
    return retrieve_with_plan(cfg, question, topk=topk, neighbor_window=neighbor_window)


def build_context_view(hits: List[Hit]) -> str:
    return format_hits(hits)


def render_answer_view(hits: List[Hit], latency_ms: int) -> str:
    header = f"[retrieval] hits={len(hits)} latency_ms={latency_ms}"
    body = build_context_view(hits)
    return header + "\n\n" + body if body else header


def query(cfg: AppConfig, question: str, topk: int | None = None, neighbor_window: int | None = None) -> str:
    hits, latency = retrieve_only(cfg, question, topk=topk, neighbor_window=neighbor_window)
    return render_answer_view(hits, latency)


__all__ = [
    "retrieve_only",
    "retrieve_only_with_plan",
    "build_context_view",
    "render_answer_view",
    "query",
    "generate_answer",
    "hits_to_sources",
    "source_from_hit",
]
