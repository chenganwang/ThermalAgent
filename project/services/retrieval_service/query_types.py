from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re


def focus_retrieval_query(query: str) -> str:
    """Exclude explicit contrast clauses from positive retrieval evidence.

    The original user request stays in QueryPlan.original_query. Only a clause
    after a separator is removed, so questions such as “为什么不是黑体” retain
    their meaning. This is deterministic query handling, not answer rejection.
    """
    text = str(query or "").strip()
    focused = re.sub(r"[,，;；]\s*(?:而不是|不是|而非|并非)[^,，;；。?？]+", "", text)
    return focused.strip() or text


@dataclass
class QueryPlan:
    original_query: str
    rewritten_queries: list[str] = field(default_factory=list)
    keyword_queries: list[str] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)
    intent: str = "general"
    prefer_chunk_types: list[str] = field(default_factory=list)
    preserved_tokens: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def vector_queries(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for q in [self.original_query, *self.rewritten_queries, *self.sub_queries]:
            s = focus_retrieval_query(q)
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    def bm25_queries(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for q in [self.original_query, *self.keyword_queries]:
            s = focus_retrieval_query(q)
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    def to_dict(self) -> dict:
        return asdict(self)
