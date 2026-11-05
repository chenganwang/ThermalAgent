from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class DictSerializable:
    """Small mixin for dataclasses exposed through API-compatible dicts."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskResult(DictSerializable):
    task_type: str
    domain: str = "thermal_management"
    entities: list[str] = field(default_factory=list)
    intent: str = ""
    needs_retrieval: bool = True
    needs_calculation: bool = False
    needs_visualization: bool = False
    confidence: float = 0.5
    original_query: str = ""
    normalized_query: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RewriteResult(DictSerializable):
    original_query: str
    rewritten_query: str
    expanded_queries: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceRef(DictSerializable):
    rank: int | None = None
    doc_id: int | None = None
    chunk_id: int | None = None
    chunk_index: int | None = None
    title: str | None = None
    book_title: str | None = None
    chapter: str | None = None
    section: str | None = None
    section_path: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    chunk_type: str | None = None
    doc_type: str | None = None
    organization: str | None = None
    language: str | None = None
    publish_year: int | None = None
    source: str | None = None
    url: str | None = None
    local_path: str | None = None
    score: float | None = None
    text_preview: str | None = None


@dataclass(frozen=True)
class RetrievalMetadata(DictSerializable):
    retrieval_count: int = 0
    retrieval_latency_ms: int = 0
    retrieval_error: str | None = None
    retrieval_plan: dict[str, Any] | None = None
    used_memory: bool = False
    used_calculation: bool = False
    llm_enabled: bool = False


@dataclass(frozen=True)
class RetrievalPlan(DictSerializable):
    original_query: str
    rewritten_queries: list[str] = field(default_factory=list)
    keyword_queries: list[str] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)
    prefer_chunk_types: list[str] = field(default_factory=list)
    intent: str = "general"


@dataclass(frozen=True)
class RetrievedChunk(DictSerializable):
    score: float
    doc_id: int
    chunk_id: int
    chunk_index: int
    text: str = ""
    expanded_text: str = ""
    chunk_type: str = "text"
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    vector_score: float = 0.0
    bm25_score: float = 0.0
    lexical_score: float = 0.0
    neighbors: list[dict[str, Any]] = field(default_factory=list)
    retrieval_routes: list[str] = field(default_factory=list)
    exact_reference_matches: list[str] = field(default_factory=list)
    meta_json: str | None = None


@dataclass(frozen=True)
class FactExtractionResult(DictSerializable):
    has_facts: bool = False
    fact_type: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DomainRuleResult(DictSerializable):
    matched: bool = False
    rule_name: str | None = None
    entities: list[str] = field(default_factory=list)
    expanded_queries: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    rerank_bonus: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentAnswer(DictSerializable):
    answer: str
    task: dict[str, Any]
    rewrite: dict[str, Any]
    sources: list[dict[str, Any]]
    session_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
