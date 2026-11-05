from __future__ import annotations

from typing import Any

from ..config import AppConfig
from ..retriever import Hit, retrieve_with_plan
from .retrieval_types import RetrievalRunResult


def retrieve_for_agent_result(cfg: AppConfig, query: str, top_k: int) -> RetrievalRunResult:
    """Return an explicit retrieval boundary object for agent orchestration."""

    hits, latency_ms, plan = retrieve_with_plan(cfg, query, topk=top_k)
    return RetrievalRunResult(hits=hits, latency_ms=latency_ms, plan=plan)


def retrieve_for_agent(cfg: AppConfig, query: str, top_k: int) -> tuple[list[Hit], int, Any]:
    """Adapter used by ThermalAgent so orchestration stays independent."""

    return retrieve_for_agent_result(cfg, query, top_k).to_agent_tuple()
