"""Rule-based knowledge unit candidate extraction for ingest dry-runs."""

from .contracts import KnowledgeUnitCandidate, VALID_UNIT_TYPES
from .extractor import extract_knowledge_units_from_chunk, extract_knowledge_units_from_chunks

__all__ = [
    "KnowledgeUnitCandidate",
    "VALID_UNIT_TYPES",
    "extract_knowledge_units_from_chunk",
    "extract_knowledge_units_from_chunks",
]
