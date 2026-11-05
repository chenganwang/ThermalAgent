from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class RetrievalRequest:
    """Boundary object for retrieval calls.

    This object carries request parameters only. It intentionally does not
    access MySQL, FAISS, BM25, or local index files.
    """

    query: str
    topk: int | None = None
    neighbor_window: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalRunResult:
    """Stable result envelope between agent orchestration and retrieval."""

    hits: list[Any] = field(default_factory=list)
    latency_ms: int = 0
    plan: Any = None
    error: str | None = None

    def to_agent_tuple(self) -> tuple[list[Any], int, Any]:
        return self.hits, self.latency_ms, self.plan

    def to_dict(self) -> dict[str, Any]:
        plan = self.plan.to_dict() if hasattr(self.plan, "to_dict") else self.plan
        return {
            "hits_count": len(self.hits),
            "latency_ms": self.latency_ms,
            "plan": plan,
            "error": self.error,
        }


@dataclass(frozen=True)
class RetrievalHitSnapshot:
    """Serializable snapshot of a Hit-like object without DB/index access."""

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceRecord:
    """Document source contract used by agent responses."""

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

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SourceRecord":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: data.get(key) for key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot_hit(hit: Any) -> RetrievalHitSnapshot:
    """Copy public Hit-like fields without mutating the input object."""

    return RetrievalHitSnapshot(
        score=float(getattr(hit, "score", 0.0) or 0.0),
        vector_score=float(getattr(hit, "vector_score", 0.0) or 0.0),
        bm25_score=float(getattr(hit, "bm25_score", 0.0) or 0.0),
        lexical_score=float(getattr(hit, "lexical_score", 0.0) or 0.0),
        doc_id=int(getattr(hit, "doc_id", 0) or 0),
        chunk_id=int(getattr(hit, "chunk_id", 0) or 0),
        chunk_index=int(getattr(hit, "chunk_index", 0) or 0),
        page_start=getattr(hit, "page_start", None),
        page_end=getattr(hit, "page_end", None),
        chunk_type=str(getattr(hit, "chunk_type", "text") or "text"),
        text=str(getattr(hit, "text", "") or ""),
        expanded_text=str(getattr(hit, "expanded_text", "") or ""),
        section_path=getattr(hit, "section_path", None),
        neighbors=list(getattr(hit, "neighbors", []) or []),
        retrieval_routes=list(getattr(hit, "retrieval_routes", []) or []),
        exact_reference_matches=list(getattr(hit, "exact_reference_matches", []) or []),
        meta_json=getattr(hit, "meta_json", None),
    )


def snapshot_hits(hits: Sequence[Any]) -> list[RetrievalHitSnapshot]:
    return [snapshot_hit(hit) for hit in hits]
