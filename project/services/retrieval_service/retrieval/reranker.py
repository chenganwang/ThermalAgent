from __future__ import annotations

from ..domain_rules.rule_registry import rerank_bonus


def domain_rerank_bonus(query: str, text: str, chunk_type: str = "text") -> float:
    """Return domain-specific rerank bonus without coupling retriever to rules."""

    return rerank_bonus(query, text, chunk_type)
