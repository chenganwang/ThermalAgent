from __future__ import annotations

from typing import Any, Callable

from ...answering.source_formatter import filter_sources_for_query, hits_to_sources
from ...query_rewriter import QueryRewriteResult
from ..metadata_builder import safe_error
from ..state import AgentContext
from .base import BaseAgentStage


class RetrievalStage(BaseAgentStage):
    """Wrap the existing retrieval and source-formatting flow."""

    name = "retrieval"

    def __init__(
        self,
        *,
        cfg: Any = None,
        retriever_func: Callable[[Any, str, int], tuple[list[Any], int, Any]] | None = None,
        source_builder: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.retriever_func = retriever_func
        self.source_builder = source_builder or hits_to_sources

    def run(self, context: AgentContext) -> AgentContext:
        task = dict(context.task or {})
        if not bool(task.get("needs_retrieval")) or not context.request.query.strip():
            return self._record_result(context, hits=[], sources=[], latency_ms=0, query=None, plan=None, error=None)

        retrieval_query = self._retrieval_query(context)
        try:
            if self.retriever_func is None:
                raise RuntimeError("retriever_func_not_configured")
            hits, latency_ms, plan = self.retriever_func(
                self.cfg,
                retrieval_query,
                int(context.request.top_k),
            )
        except Exception as exc:
            error = safe_error(exc)
            context.errors.append(f"{self.name}: {error}")
            return self._record_result(
                context,
                hits=[],
                sources=[],
                latency_ms=0,
                query=retrieval_query,
                plan=None,
                error=error,
            )

        hit_values = list(hits or [])
        raw_sources = list(self.source_builder(hit_values, cfg=self.cfg) or [])
        if len(raw_sources) != len(hit_values) or not all(isinstance(source, dict) for source in raw_sources):
            raise TypeError("retrieval_sources_must_match_hits")
        source_values = filter_sources_for_query(
            context.request.query,
            raw_sources,
        )
        if not all(isinstance(source, dict) for source in source_values):
            raise TypeError("retrieval_sources_must_be_dicts")
        # Filtering/reordering cards is also an evidence decision. Keep the
        # underlying chunks in that exact order so fact extraction cannot use
        # rejected evidence and inline citation numbers still identify cards.
        aligned_hits = []
        for rank, source in enumerate(source_values, start=1):
            original_index = next(index for index, original in enumerate(raw_sources) if original == source)
            aligned_hits.append(hit_values[original_index])
            source["rank"] = rank
        plan_data = plan.to_dict() if hasattr(plan, "to_dict") else None
        return self._record_result(
            context,
            hits=aligned_hits,
            sources=source_values,
            latency_ms=int(latency_ms or 0),
            query=retrieval_query,
            plan=plan_data,
            error=None,
        )

    @staticmethod
    def _retrieval_query(context: AgentContext) -> str:
        rewrite_result = context.intermediate.get("rewrite_result")
        if not isinstance(rewrite_result, QueryRewriteResult):
            rewrite = dict(context.rewrite or {})
            rewrite_result = QueryRewriteResult(
                original_query=str(rewrite.get("original_query") or context.request.query),
                rewritten_query=str(rewrite.get("rewritten_query") or context.request.query),
                expanded_queries=list(rewrite.get("expanded_queries") or []),
                keywords=list(rewrite.get("keywords") or []),
                entities=list(rewrite.get("entities") or []),
            )
        from ..pipeline import build_retrieval_query

        return build_retrieval_query(rewrite_result)

    @staticmethod
    def _record_result(
        context: AgentContext,
        *,
        hits: list[Any],
        sources: list[dict[str, Any]],
        latency_ms: int,
        query: str | None,
        plan: dict[str, Any] | None,
        error: str | None,
    ) -> AgentContext:
        context.sources = sources
        context.intermediate["retrieval_hits"] = hits
        context.intermediate["retrieval_result"] = {
            "query": query,
            "hits_count": len(hits),
            "source_count": len(sources),
            "latency_ms": latency_ms,
            "plan": plan,
            "error": error,
        }
        return context


__all__ = ["RetrievalStage"]
