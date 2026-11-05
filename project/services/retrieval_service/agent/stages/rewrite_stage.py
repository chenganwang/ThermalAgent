from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...config import load_config
from ...query_analyzer import analyze_query
from ...query_rewriter import QueryRewriteResult, rewrite_query
from ..metadata_builder import safe_error
from ..state import AgentContext
from .base import BaseAgentStage


RewriteFunc = Callable[[str, Any], Any]
AnalyzeFunc = Callable[[str], Any]


def _default_analyze(query: str) -> Any:
    return analyze_query(load_config(), query)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        if isinstance(mapped, dict):
            return dict(mapped)
    return {}


def _normalize_rewrite_dict(
    result: Any,
    *,
    query: str,
    query_plan: Any = None,
) -> dict[str, Any]:
    rewrite = _as_dict(result)
    plan = _as_dict(query_plan)
    original_query = str(rewrite.get("original_query") or query or "")
    rewritten_query = str(rewrite.get("rewritten_query") or original_query)
    expanded_queries = [str(item) for item in rewrite.get("expanded_queries") or [] if item]
    expanded_query = str(
        rewrite.get("expanded_query")
        or (expanded_queries[0] if expanded_queries else rewritten_query)
    )

    rewrite["original_query"] = original_query
    rewrite["rewritten_query"] = rewritten_query
    rewrite["expanded_queries"] = expanded_queries
    rewrite["expanded_query"] = expanded_query
    rewrite["preserved_tokens"] = [
        str(item)
        for item in rewrite.get("preserved_tokens") or plan.get("preserved_tokens") or []
        if item
    ]
    if plan:
        rewrite["query_plan"] = plan
        rewrite["search_terms"] = [str(item) for item in plan.get("keyword_queries") or [] if item]
    return rewrite


class RewriteStage(BaseAgentStage):
    """Build query rewrite context without changing retrieval behavior."""

    name = "rewrite"

    def __init__(
        self,
        rewrite_func: RewriteFunc | None = None,
        analyze_func: AnalyzeFunc | None = None,
    ) -> None:
        self._rewrite_func = rewrite_func or rewrite_query
        self._analyze_func = analyze_func or _default_analyze

    def run(self, context: AgentContext) -> AgentContext:
        query = context.request.query
        task = dict(context.task or {})
        try:
            result = self._rewrite_func(query, task)
        except Exception as exc:
            error = safe_error(exc)
            context.errors.append(f"{self.name}: {error}")
            result = QueryRewriteResult(
                original_query=query,
                rewritten_query=query,
                expanded_queries=[query] if query else [],
            )
            context.rewrite = _normalize_rewrite_dict(result, query=query)
            context.intermediate["rewrite_result"] = result
            context.intermediate["rewrite_error"] = error
            context.intermediate["rewrite_plan"] = None
            return context

        plan = None
        try:
            plan = self._analyze_func(query)
        except Exception as exc:
            context.errors.append(f"{self.name}_analysis: {safe_error(exc)}")

        context.rewrite = _normalize_rewrite_dict(result, query=query, query_plan=plan)
        context.intermediate["rewrite_result"] = result
        context.intermediate["rewrite_error"] = None
        context.intermediate["rewrite_plan"] = plan
        context.intermediate["rewrite_plan_dict"] = _as_dict(plan)
        return context


__all__ = ["RewriteStage"]
