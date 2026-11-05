from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Sequence

from ..config import AppConfig
from ..db import DB

try:
    from services.ingest_service.chunking.pack import strip_packed_meta
except Exception:  # pragma: no cover - defensive fallback for partial installs
    def strip_packed_meta(text: str) -> str:
        return text or ""


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except Exception:
        return None


def clean_preview(text: str, limit: int = 180) -> str:
    cleaned = strip_packed_meta(text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^\[(HIT|CTX)\]\s*", "", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def parse_meta_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def section_parts(section_path: str | None) -> tuple[str | None, str | None]:
    if not section_path:
        return None, None
    parts = [x.strip() for x in re.split(r"[>/|\\]+", str(section_path)) if x.strip()]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[-1]


def _document_meta(raw: Any) -> dict[str, Any]:
    meta = parse_meta_json(raw)
    return meta if isinstance(meta, dict) else {}


def document_title_map(cfg: AppConfig | None, doc_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    if cfg is None or not doc_ids:
        return {}
    unique_ids = sorted({int(x) for x in doc_ids if x is not None})
    if not unique_ids:
        return {}
    try:
        db = DB.create(cfg)
        placeholders = ",".join(["%s"] * len(unique_ids))
        rows = db.fetchall(
            f"""
            SELECT id, title, source, doc_type, organization, language,
                   publish_year, url, local_path, meta_json
            FROM documents
            WHERE id IN ({placeholders})
            """,
            tuple(unique_ids),
        )
    except Exception:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for doc_id, title, source, doc_type, organization, language, publish_year, url, local_path, meta_json in rows:
        source_text = str(source) if source else None
        fallback_title = Path(source_text).name if source_text else None
        doc_meta = _document_meta(meta_json)
        out[int(doc_id)] = {
            "title": str(title) if title else fallback_title,
            "source": source_text,
            "doc_type": str(doc_type) if doc_type else doc_meta.get("doc_type"),
            "organization": str(organization) if organization else doc_meta.get("organization"),
            "language": str(language) if language else doc_meta.get("language"),
            "publish_year": int(publish_year) if publish_year is not None else doc_meta.get("publish_year"),
            "url": str(url) if url else doc_meta.get("url"),
            "local_path": str(local_path) if local_path else doc_meta.get("local_path"),
            "meta_json": doc_meta,
        }
    return out


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def source_from_hit(hit: Any, *, rank: int | None = None, doc_info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert a retriever Hit into a stable source-tracking object.

    This is intentionally additive: existing keys are preserved, while the
    rag_agent documents metadata is exposed when available.
    """

    chunk_meta = parse_meta_json(getattr(hit, "meta_json", None))
    doc_meta = parse_meta_json((doc_info or {}).get("meta_json")) if doc_info else {}
    meta = {**doc_meta, **chunk_meta}
    chapter, section = section_parts(getattr(hit, "section_path", None))
    title = _first_value(
        meta.get("title"),
        meta.get("book_title"),
        meta.get("document_title"),
        (doc_info or {}).get("title"),
    )
    book_title = _first_value(meta.get("book_title"), title)
    source = _first_value(meta.get("source"), (doc_info or {}).get("source"))
    url = _first_value(meta.get("url"), (doc_info or {}).get("url"))
    local_path = _first_value(meta.get("local_path"), (doc_info or {}).get("local_path"), source)
    return {
        "rank": rank,
        "doc_id": getattr(hit, "doc_id", None),
        "chunk_id": getattr(hit, "chunk_id", None),
        "chunk_index": getattr(hit, "chunk_index", None),
        "title": title,
        "book_title": book_title,
        "chapter": _first_value(meta.get("chapter"), meta.get("chapter_title"), chapter),
        "section": _first_value(meta.get("section"), meta.get("section_title"), section),
        "section_path": getattr(hit, "section_path", None),
        "page_start": getattr(hit, "page_start", None),
        "page_end": getattr(hit, "page_end", None),
        "chunk_type": getattr(hit, "chunk_type", None),
        "doc_type": _first_value(meta.get("doc_type"), (doc_info or {}).get("doc_type")),
        "organization": _first_value(meta.get("organization"), (doc_info or {}).get("organization")),
        "language": _first_value(meta.get("language"), (doc_info or {}).get("language")),
        "publish_year": _first_value(meta.get("publish_year"), (doc_info or {}).get("publish_year")),
        "source": source,
        "url": url,
        "local_path": local_path,
        "score": _safe_float(getattr(hit, "score", None)),
        "text_preview": clean_preview(getattr(hit, "text", "") or getattr(hit, "expanded_text", "")),
    }


def hits_to_sources(hits: Sequence[Any], cfg: AppConfig | None = None) -> list[dict[str, Any]]:
    """Build stable source objects while tolerating missing DB metadata."""

    doc_map = document_title_map(cfg, [int(getattr(hit, "doc_id")) for hit in hits if getattr(hit, "doc_id", None) is not None])
    sources: list[dict[str, Any]] = []
    for rank, hit in enumerate(hits, start=1):
        doc_id = int(getattr(hit, "doc_id")) if getattr(hit, "doc_id", None) is not None else None
        sources.append(source_from_hit(hit, rank=rank, doc_info=doc_map.get(doc_id or -1)))
    return sources


_NOISY_SOURCE_RE = re.compile(
    r"[\uFFFD□]{2,}|([\u4e00-\u9fffA-Za-z])\1{8,}|(?:哇|啊|噢|嗯){6,}",
    re.IGNORECASE,
)


def _source_identity(source: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _first_value(source.get("document_id"), source.get("doc_id")),
        source.get("page_start"),
        source.get("page_end"),
        _first_value(source.get("chunk_id"), source.get("chunk_index")),
    )


def _source_search_text(source: dict[str, Any]) -> str:
    values = [
        source.get("title"),
        source.get("book_title"),
        source.get("chapter"),
        source.get("section"),
        source.get("section_path"),
        source.get("text_preview"),
    ]
    return " ".join(str(value) for value in values if value).lower()


def _is_noisy_source(source: dict[str, Any]) -> bool:
    preview = str(source.get("text_preview") or "")
    if not preview.strip():
        return False
    return bool(_NOISY_SOURCE_RE.search(preview))


def _topic_terms(query: str) -> tuple[str, ...]:
    lowered = (query or "").lower()
    if any(term in lowered for term in ("傅里叶", "fourier", "导热定律")):
        return (
            "傅里叶",
            "fourier",
            "导热",
            "conduction",
            "heat flux",
            "温度梯度",
            "temperature gradient",
            "thermal conductivity",
        )
    if any(term in lowered for term in ("雷诺数", "reynolds")):
        return (
            "雷诺",
            "reynolds",
            "层流",
            "laminar",
            "过渡",
            "transition",
            "湍流",
            "turbulent",
            "管内流动",
            "pipe flow",
        )
    if any(term in lowered for term in ("平壁", "稳态导热", "导热量", "热流量", "传热量", "plane wall")):
        return (
            "平壁",
            "plane wall",
            "稳态导热",
            "steady conduction",
            "导热量",
            "heat rate",
            "导热",
            "conduction",
            "thermal conductivity",
        )
    return ()


def filter_sources_for_query(
    query: str,
    sources: Sequence[dict[str, Any]],
    *,
    max_sources: int = 5,
) -> list[dict[str, Any]]:
    """Deduplicate and suppress obvious source noise for the current query."""

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source in sources or []:
        if not isinstance(source, dict) or _is_noisy_source(source):
            continue
        key = _source_identity(source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(source))

    terms = _topic_terms(query)
    if not terms:
        return deduped[:max_sources]

    scored: list[tuple[int, dict[str, Any]]] = []
    for source in deduped:
        text = _source_search_text(source)
        score = sum(1 for term in terms if term.lower() in text)
        if score > 0:
            scored.append((score, source))
    scored.sort(key=lambda item: (-item[0], int(item[1].get("rank") or 9999)))
    return [source for _score, source in scored[:max_sources]]


def source_summary(sources: Sequence[dict[str, Any]], limit: int = 3) -> str:
    labels: list[str] = []
    for src in list(sources)[:limit]:
        rank = src.get("rank")
        title = src.get("title") or src.get("book_title") or f"doc_id={src.get('doc_id')}"
        chapter = src.get("chapter")
        page_start = src.get("page_start")
        page_end = src.get("page_end")
        loc = f", {chapter}" if chapter else ""
        if page_start and page_end:
            labels.append(f"[{rank}] {title}{loc}, p.{page_start}-{page_end}")
        else:
            labels.append(f"[{rank}] {title}{loc}")
    return "；".join(labels)
