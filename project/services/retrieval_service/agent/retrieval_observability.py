from __future__ import annotations

import math
import re
from typing import Any


_LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]")


def _safe_label(value: Any, *, limit: int = 160) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    if not text or _LOCAL_PATH.search(text):
        return None
    return text[:limit]


def _safe_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) else None


def build_retrieval_observability(
    query: str,
    retrieval_query: str | None,
    sources: list[dict[str, Any]] | None,
    hits: list[Any] | None = None,
) -> dict[str, Any]:
    """Build JSON-safe retrieval statistics without copying source bodies."""

    source_values = list(sources or [])
    source_titles: list[str] = []
    source_kinds: list[str] = []
    scores: list[float] = []
    warnings: list[str] = []

    for source in source_values:
        if not isinstance(source, dict):
            warnings.append("non_dict_source_ignored")
            continue
        title = _safe_label(source.get("title") or source.get("book_title"))
        if title and title not in source_titles and len(source_titles) < 8:
            source_titles.append(title)
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        kind = _safe_label(source.get("chunk_type") or source.get("doc_type") or metadata.get("kind"), limit=80)
        if kind and kind not in source_kinds and len(source_kinds) < 8:
            source_kinds.append(kind)
        score = _safe_score(source.get("score"))
        if score is not None:
            scores.append(score)

    if not source_values:
        warnings.append("no_sources")

    return {
        "enabled": True,
        "source_count": len(source_values),
        "has_sources": bool(source_values),
        "query_present": bool(str(query or "").strip()),
        "retrieval_query_present": bool(str(retrieval_query or "").strip()),
        "source_titles": source_titles,
        "source_kinds": source_kinds,
        "score_summary": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "count": len(scores),
        },
        "hit_count": len(list(hits or [])),
        "warnings": list(dict.fromkeys(warnings)),
    }


__all__ = ["build_retrieval_observability"]
