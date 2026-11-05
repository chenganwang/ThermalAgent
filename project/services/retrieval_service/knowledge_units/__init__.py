"""Optional read-only knowledge_units shadow retrieval adapter.

This package is intentionally not imported by the main retrieval or agent
pipeline. Callers must opt in from evaluation/shadow scripts.
"""

from __future__ import annotations

from .adapter import KnowledgeUnitsRetrievalAdapter, search_knowledge_units_shadow
from .evaluation import run_shadow_evaluation
from .schema import KnowledgeUnitHit, KnowledgeUnitSearchResult

__all__ = [
    "KnowledgeUnitHit",
    "KnowledgeUnitSearchResult",
    "KnowledgeUnitsRetrievalAdapter",
    "run_shadow_evaluation",
    "search_knowledge_units_shadow",
]
