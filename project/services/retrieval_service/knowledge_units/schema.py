from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_loads_maybe(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_default(value: Any) -> str:
    return str(value)


@dataclass(frozen=True)
class KnowledgeUnitHit:
    unit_code: str | None
    dedup_key: str | None
    unit_type: str | None
    canonical_name: str | None
    content: str | None
    document_id: Any
    source_chunk_id: Any
    provenance_status: str
    match_reason: str
    score: float = 0.0
    score_breakdown: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_code": self.unit_code,
            "dedup_key": self.dedup_key,
            "unit_type": self.unit_type,
            "canonical_name": self.canonical_name,
            "content": self.content,
            "document_id": self.document_id,
            "source_chunk_id": self.source_chunk_id,
            "provenance_status": self.provenance_status,
            "match_reason": self.match_reason,
            "score": self.score,
            "score_breakdown": dict(self.score_breakdown),
        }


@dataclass(frozen=True)
class KnowledgeUnitSearchResult:
    query: str
    unit_type_filter: list[str] = field(default_factory=list)
    status: str = "ok"
    enabled: bool = True
    hits: list[KnowledgeUnitHit] = field(default_factory=list)
    error_type: str | None = None
    error: str | None = None
    schema_fields: list[str] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)
    query_debug_info: dict[str, Any] = field(default_factory=dict)
    db_connection_opened: bool = False
    database_written: bool = False
    readonly: bool = True
    default_agent_dependency: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "enabled": self.enabled,
            "query": self.query,
            "unit_type_filter": list(self.unit_type_filter),
            "hit_count": len(self.hits),
            "hits": [hit.to_dict() for hit in self.hits],
            "error_type": self.error_type,
            "error": self.error,
            "schema_fields": list(self.schema_fields),
            "query_terms": list(self.query_terms),
            "query_debug_info": dict(self.query_debug_info),
            "db_connection_opened": self.db_connection_opened,
            "database_written": self.database_written,
            "readonly": self.readonly,
            "default_agent_dependency": self.default_agent_dependency,
        }
        return json.loads(json.dumps(payload, ensure_ascii=False, default=_json_default))


def hit_from_row(
    row: dict[str, Any],
    *,
    match_reason: str,
    score: float = 0.0,
    score_breakdown: dict[str, Any] | None = None,
) -> KnowledgeUnitHit:
    meta = _json_loads_maybe(row.get("meta_json"))
    unit_code = _text(row.get("unit_code")) or None
    dedup_key = _text(row.get("dedup_key") or meta.get("dedup_key")) or None
    canonical_name = _text(row.get("canonical_name") or meta.get("canonical_name") or row.get("title")) or None
    document_id = row.get("document_id") if row.get("document_id") is not None else row.get("source_doc_id")
    if document_id is None:
        document_id = meta.get("document_id")
    source_chunk_id = row.get("source_chunk_id") if row.get("source_chunk_id") is not None else meta.get("source_chunk_id")
    provenance_status = _text(row.get("provenance_status") or meta.get("provenance_status"))
    if not provenance_status:
        provenance_status = "ready" if document_id not in (None, "") and source_chunk_id not in (None, "") else "unknown"

    return KnowledgeUnitHit(
        unit_code=unit_code,
        dedup_key=dedup_key,
        unit_type=_text(row.get("unit_type") or meta.get("unit_type")) or None,
        canonical_name=canonical_name,
        content=_text(row.get("content")) or None,
        document_id=document_id,
        source_chunk_id=source_chunk_id,
        provenance_status=provenance_status,
        match_reason=match_reason,
        score=float(score),
        score_breakdown=dict(score_breakdown or {}),
    )


__all__ = [
    "KnowledgeUnitHit",
    "KnowledgeUnitSearchResult",
    "hit_from_row",
]
