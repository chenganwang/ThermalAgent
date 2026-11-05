from __future__ import annotations

from collections.abc import Sequence

from .ashrae_rules import (
    append_entities,
    ashrae_expanded_queries,
    ashrae_table_fact_bonus,
    is_ashrae_query,
)


def apply_entity_rules(query: str, entities: Sequence[str] | None = None) -> list[str]:
    """Apply registered domain rules that add canonical entities."""

    out = list(entities or [])
    out = append_entities(query, out)
    return out


def is_domain_specific_query(query: str, entities: Sequence[str] | None = None) -> bool:
    return is_ashrae_query(query, entities)


def expanded_queries(query: str, entities: Sequence[str] | None = None) -> list[str]:
    if is_ashrae_query(query, entities):
        return ashrae_expanded_queries(query, entities)
    return []


def rerank_bonus(query: str, text: str, chunk_type: str = "text") -> float:
    return ashrae_table_fact_bonus(query, text, chunk_type)
