from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Sequence, Tuple

import numpy as np

from .bm25_index import BM25IndexManager
from services.ingest_service.chunking.pack import strip_packed_meta
from .config import AppConfig
from .db import DB
from .embed_index import FaissIndexManager, build_embeddings, get_embedder
from .query_analyzer import analyze_query
from .query_types import QueryPlan, focus_retrieval_query
from .retrieval.reranker import domain_rerank_bonus
from .indexing.active_bundle import ActiveIndexBundle, resolve_active_bundle


logger = logging.getLogger(__name__)


@dataclass
class Hit:
    score: float
    vector_score: float
    bm25_score: float
    lexical_score: float
    doc_id: int
    chunk_index: int
    page_start: int
    page_end: int
    chunk_id: int
    chunk_type: str = "text"
    text: str = ""
    expanded_text: str = ""
    neighbors: list[dict] = field(default_factory=list)
    section_path: str | None = None
    token_len: int | None = None
    vector_pos: int | None = None
    retrieval_routes: list[str] = field(default_factory=list)
    exact_reference_matches: list[str] = field(default_factory=list)
    meta_json: str | None = None


_DEF_PAT = re.compile(r"(称为|定义为|即|公式为|表达式为|可表示为)")
_REF_PAT = re.compile(r"(?:图|表|式)\s*\d+(?:\s*[-－–\.]\s*\d+)*")


def _tokenize_query(q: str) -> List[str]:
    q = (q or "").strip()
    if not q:
        return []
    words = re.findall(r"[A-Za-z0-9_./+\-=]+", q)
    cjk = re.findall(r"[\u4e00-\u9fff]", q)
    bigrams = ["".join(cjk[i : i + 2]) for i in range(len(cjk) - 1)]
    toks: list[str] = []
    toks.extend(words)
    toks.extend(bigrams)
    seen = set()
    out: list[str] = []
    for t in toks:
        t = t.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _chunk_type_bonus(query: str, text: str, chunk_type: str) -> float:
    toks = _tokenize_query(query)
    if not toks:
        return 0.0
    hit_count = sum(1 for tok in toks if tok in text)
    bonus = 0.0
    if chunk_type in {"table", "table_summary"} and hit_count:
        bonus += min(0.20, 0.05 * hit_count)
    if chunk_type == "text" and _DEF_PAT.search(text):
        bonus += 0.06
    return bonus


def _lexical_bonus(query: str, text: str, chunk_type: str = "text") -> float:
    q = (query or "").strip()
    t = (text or "")
    if not q or not t:
        return 0.0

    bonus = 0.0
    if q in t:
        bonus += 0.35

    toks = _tokenize_query(q)
    hit = sum(1 for tok in toks if tok in t)
    if hit:
        bonus += min(0.35, 0.08 * hit)

    if _DEF_PAT.search(t):
        bonus += 0.05

    bonus += _chunk_type_bonus(q, t, chunk_type)
    return bonus


def _ashrae_table_fact_bonus(query: str, text: str, chunk_type: str = "text") -> float:
    """Compatibility wrapper for ASHRAE/domain-specific rerank rules."""

    return domain_rerank_bonus(query, text, chunk_type)


def _clean_text_for_match(text: str) -> str:
    return strip_packed_meta(text or "")


def _normalize_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmax - vmin < 1e-12:
        return [1.0 if vmax > 0 else 0.0 for _ in values]
    return [(v - vmin) / (vmax - vmin) for v in values]


def _add_route(hit: Hit, route: str) -> None:
    route = (route or "").strip()
    if route and route not in hit.retrieval_routes:
        hit.retrieval_routes.append(route)


def _add_exact_match(hit: Hit, token: str) -> None:
    token = (token or "").strip()
    if token and token not in hit.exact_reference_matches:
        hit.exact_reference_matches.append(token)


def _normalize_reference_token(token: str) -> str:
    s = (token or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("－", "-").replace("–", "-").replace("—", "-").replace(".", "-")
    s = re.sub(r"\s+", "", s)
    return s


def _normalize_reference_blob(text: str) -> str:
    s = _normalize_reference_token(text)
    return s.lower()


def _reference_target_chunk_types(token: str) -> tuple[str, ...]:
    if token.startswith("图"):
        return ("figure", "text")
    if token.startswith("表"):
        return ("table", "table_summary", "text")
    return ("text", "table", "table_summary")


def _intent_chunk_type_bonus(plan: QueryPlan | None, hit: Hit) -> float:
    if plan is None:
        return 0.0
    intent = plan.intent
    ctype = hit.chunk_type
    bonus = 0.0
    if intent in {"concept", "mechanism", "physical_meaning"}:
        if ctype == "text":
            bonus += 0.10
        elif ctype in {"table", "table_summary"}:
            bonus -= 0.03
    elif intent in {"formula", "applicability"}:
        if ctype == "text":
            bonus += 0.12
        elif ctype in {"table", "table_summary"}:
            bonus -= 0.02
    elif intent == "figure_lookup":
        if ctype == "figure":
            bonus += 0.18
        elif ctype == "text":
            bonus += 0.06
    elif intent in {"table_lookup", "property_lookup"}:
        if ctype in {"table", "table_summary"}:
            bonus += 0.16
        elif ctype == "text":
            bonus += 0.03
    elif intent == "example":
        if ctype == "text":
            bonus += 0.07
    return bonus


def retrieve_vector_candidates(
    cfg: AppConfig,
    question: str,
    *,
    topk: int,
    db: DB | None = None,
    route: str = "vector:original",
    bundle: ActiveIndexBundle | None = None,
) -> tuple[list[Hit], int, DB, int]:
    bundle = bundle or resolve_active_bundle(cfg)
    cfg = bundle.cfg
    db = db or DB.create(cfg)
    qvec = build_embeddings(cfg, [question], strip_meta=False)
    qvec = np.asarray(qvec, dtype=np.float32)
    faiss_topn = max(cfg.retrieval.faiss_topn_base, topk * cfg.retrieval.faiss_topn_multiplier)
    fim = FaissIndexManager(cfg)
    index = fim.load_or_create(int(qvec.shape[1]))
    scores, ids = index.search(qvec, faiss_topn)
    ids0 = [int(x) for x in ids[0].tolist() if int(x) >= 0]
    sc0 = [float(x) for x in scores[0].tolist()[: len(ids0)]]

    candidates: list[Hit] = []
    for vpos, s in zip(ids0, sc0):
        mapping = bundle.mapping_chunk_ids
        chunk_id = mapping[vpos] if mapping is not None and 0 <= vpos < len(mapping) else (
            db.vectorpos_to_chunk(int(vpos)) if mapping is None else None
        )
        if chunk_id is None:
            continue
        row = db.get_chunk_full_by_id(int(chunk_id))
        if not row:
            continue
        _, doc_id, chunk_idx, ps, pe, chunk_type, text, token_len, section_path, _content_hash, _meta_json = row
        hit = Hit(
            score=float(s),
            vector_score=float(s),
            bm25_score=0.0,
            lexical_score=0.0,
            doc_id=int(doc_id),
            chunk_index=int(chunk_idx),
            page_start=int(ps or 0),
            page_end=int(pe or ps or 0),
            chunk_id=int(chunk_id),
            chunk_type=str(chunk_type or "text"),
            text=str(text or ""),
            section_path=str(section_path) if section_path else None,
            token_len=int(token_len) if token_len is not None else None,
            vector_pos=int(vpos),
            meta_json=str(_meta_json) if _meta_json else None,
        )
        _add_route(hit, route)
        candidates.append(hit)
    return candidates, faiss_topn, db, int(qvec.shape[1])


def retrieve_bm25_candidates(cfg: AppConfig, question: str, *, db: DB | None = None, bundle: ActiveIndexBundle | None = None) -> tuple[list[tuple[int, float]], DB]:
    cfg = (bundle or resolve_active_bundle(cfg)).cfg
    db = db or DB.create(cfg)
    if not cfg.bm25.enabled:
        return [], db
    mgr = BM25IndexManager(cfg)
    return mgr.search(question, topn=cfg.bm25.topn), db


def retrieve_exact_reference_candidates(
    cfg: AppConfig,
    plan: QueryPlan,
    *,
    db: DB | None = None,
    route: str = "exact_ref",
    allowed_chunk_ids: Sequence[int] | None = None,
) -> tuple[list[Hit], DB]:
    db = db or DB.create(cfg)
    if not cfg.retrieval.exact_reference_enable:
        return [], db
    refs = [_normalize_reference_token(t) for t in plan.preserved_tokens if _REF_PAT.search(t)]
    refs = [r for r in refs if r]
    if not refs:
        return [], db

    rows = db.fetchall(
        "SELECT id, doc_id, chunk_index, page_start, page_end, chunk_type, text, token_len, section_path, content_hash, meta_json "
        "FROM chunks WHERE is_active=1 ORDER BY id"
    )

    allowed = set(allowed_chunk_ids) if allowed_chunk_ids is not None else None
    candidates: list[Hit] = []
    for row in rows:
        chunk_id, doc_id, chunk_idx, ps, pe, chunk_type, text, token_len, section_path, _content_hash, _meta_json = row
        if allowed is not None and int(chunk_id) not in allowed:
            continue
        ctype = str(chunk_type or "text")
        blob = _normalize_reference_blob(f"{section_path or ''} {text or ''}")
        matched: list[str] = []
        for ref in refs:
            if ref.lower() in blob and ctype in _reference_target_chunk_types(ref):
                matched.append(ref)
        if not matched:
            continue
        hit = Hit(
            score=0.0,
            vector_score=0.0,
            bm25_score=0.0,
            lexical_score=0.0,
            doc_id=int(doc_id),
            chunk_index=int(chunk_idx),
            page_start=int(ps or 0),
            page_end=int(pe or ps or 0),
            chunk_id=int(chunk_id),
            chunk_type=ctype,
            text=str(text or ""),
            section_path=str(section_path) if section_path else None,
            token_len=int(token_len) if token_len is not None else None,
            vector_pos=None,
            meta_json=str(_meta_json) if _meta_json else None,
        )
        _add_route(hit, route)
        for token in matched:
            _add_exact_match(hit, token)
        candidates.append(hit)
        if len(candidates) >= int(cfg.retrieval.exact_reference_limit):
            break
    return candidates, db


def _merge_candidates(
    db: DB,
    vector_hits: Sequence[Hit],
    bm25_groups: Sequence[tuple[str, Sequence[tuple[int, float]]]],
    exact_hits: Sequence[Hit] | None = None,
) -> list[Hit]:
    merged: dict[int, Hit] = {}

    def _merge_hit(h: Hit) -> None:
        current = merged.get(h.chunk_id)
        if current is None:
            merged[h.chunk_id] = h
            return
        current.vector_score = max(current.vector_score, h.vector_score)
        current.score = max(current.score, h.score)
        if current.vector_pos is None and h.vector_pos is not None:
            current.vector_pos = h.vector_pos
        if current.meta_json is None and h.meta_json is not None:
            current.meta_json = h.meta_json
        for route in h.retrieval_routes:
            _add_route(current, route)
        for token in h.exact_reference_matches:
            _add_exact_match(current, token)

    for h in vector_hits:
        _merge_hit(h)

    if exact_hits:
        for h in exact_hits:
            _merge_hit(h)

    for route, bm25_hits in bm25_groups:
        for chunk_id, bm25_score in bm25_hits:
            current = merged.get(int(chunk_id))
            if current is None:
                row = db.get_chunk_full_by_id(int(chunk_id))
                if not row:
                    continue
                _, doc_id, chunk_idx, ps, pe, chunk_type, text, token_len, section_path, _content_hash, _meta_json = row
                current = Hit(
                    score=0.0,
                    vector_score=0.0,
                    bm25_score=float(bm25_score),
                    lexical_score=0.0,
                    doc_id=int(doc_id),
                    chunk_index=int(chunk_idx),
                    page_start=int(ps or 0),
                    page_end=int(pe or ps or 0),
                    chunk_id=int(chunk_id),
                    chunk_type=str(chunk_type or "text"),
                    text=str(text or ""),
                    section_path=str(section_path) if section_path else None,
                    token_len=int(token_len) if token_len is not None else None,
                    vector_pos=None,
                    meta_json=str(_meta_json) if _meta_json else None,
                )
                merged[int(chunk_id)] = current
            current.bm25_score = max(current.bm25_score, float(bm25_score))
            _add_route(current, route)

    return list(merged.values())


def _dedupe_hits(hits: Sequence[Hit], *, topk: int) -> list[Hit]:
    out: list[Hit] = []
    seen: set[tuple[int, int]] = set()
    for h in hits:
        key = (h.doc_id, h.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= topk:
            break
    return out


def _expand_neighbors(db: DB, hit: Hit, *, window: int = 1) -> Hit:
    rows = db.list_neighbor_chunks(doc_id=hit.doc_id, chunk_index=hit.chunk_index, window=window)
    neighbors: list[dict] = []
    expanded_parts: list[str] = []
    for row in rows:
        chunk_id, doc_id, chunk_index, ps, pe, chunk_type, text, token_len, section_path, _content_hash, _meta_json = row
        cleaned = strip_packed_meta(str(text or ""))
        neighbors.append(
            {
                "chunk_id": int(chunk_id),
                "doc_id": int(doc_id),
                "chunk_index": int(chunk_index),
                "page_start": int(ps or 0),
                "page_end": int(pe or ps or 0),
                "chunk_type": str(chunk_type or "text"),
                "section_path": str(section_path) if section_path else None,
                "token_len": int(token_len) if token_len is not None else None,
                "meta_json": str(_meta_json) if _meta_json else None,
                "text": cleaned,
            }
        )
        prefix = "[HIT]" if int(chunk_index) == hit.chunk_index else "[CTX]"
        expanded_parts.append(f"{prefix} chunk={int(chunk_index)} p.{int(ps or 0)}-{int(pe or ps or 0)}\n{cleaned}")
    hit.neighbors = neighbors
    hit.expanded_text = "\n\n".join(expanded_parts)
    return hit


def rerank_candidates(
    cfg: AppConfig,
    question: str,
    candidates: Sequence[Hit],
    *,
    topk: int,
    db: DB | None = None,
    neighbor_window: int = 1,
    plan: QueryPlan | None = None,
) -> list[Hit]:
    db = db or DB.create(cfg)
    question = focus_retrieval_query(question)
    rescored: list[Hit] = []
    vec_norms = _normalize_scores([h.vector_score for h in candidates])
    bm25_norms = _normalize_scores([h.bm25_score for h in candidates])

    lexical_queries = [question]
    if plan is not None:
        lexical_queries.extend(plan.rewritten_queries[: cfg.retrieval.max_rewrite_queries])
        lexical_queries.extend(plan.keyword_queries[: cfg.retrieval.max_keyword_queries])

    for h, vnorm, bnorm in zip(candidates, vec_norms, bm25_norms):
        clean = _clean_text_for_match(h.text)
        raw_lexical = max((_lexical_bonus(focus_retrieval_query(q), clean, h.chunk_type) for q in lexical_queries if q), default=0.0)
        lexical = cfg.retrieval.lexical_weight * raw_lexical
        type_bonus = _chunk_type_bonus(question, clean, h.chunk_type)
        if plan is not None and plan.prefer_chunk_types and h.chunk_type in plan.prefer_chunk_types:
            type_bonus += cfg.retrieval.preferred_chunk_type_boost
        type_bonus += _intent_chunk_type_bonus(plan, h)
        type_bonus += _ashrae_table_fact_bonus(question, clean, h.chunk_type)
        route_bonus = 0.0
        if len(h.retrieval_routes) > 1:
            route_bonus = min(0.15, cfg.retrieval.multi_route_hit_boost * (len(h.retrieval_routes) - 1))
        exact_bonus = 0.0
        if h.exact_reference_matches:
            exact_bonus = min(0.35, cfg.retrieval.exact_reference_boost * len(h.exact_reference_matches))
            if plan is not None and plan.intent == "figure_lookup" and h.chunk_type == "figure":
                exact_bonus += 0.10
            if plan is not None and plan.intent in {"table_lookup", "property_lookup"} and h.chunk_type in {"table", "table_summary"}:
                exact_bonus += 0.10
        h.lexical_score = lexical
        h.score = cfg.retrieval.vector_weight * vnorm + cfg.retrieval.bm25_weight * bnorm + lexical + type_bonus + route_bonus + exact_bonus
        h.text = clean
        rescored.append(h)

    rescored.sort(key=lambda x: x.score, reverse=True)
    deduped = _dedupe_hits(rescored, topk=topk)
    return [_expand_neighbors(db, h, window=neighbor_window) for h in deduped]


def format_hits(hits: Sequence[Hit]) -> str:
    lines: list[str] = []
    for i, h in enumerate(hits, start=1):
        loc = f" pages {h.page_start}–{h.page_end}"
        section = f" section={h.section_path}" if h.section_path else ""
        routes = f" routes={','.join(h.retrieval_routes)}" if h.retrieval_routes else ""
        refs = f" refs={','.join(h.exact_reference_matches)}" if h.exact_reference_matches else ""
        lines.append(
            f"#{i} score={h.score:.4f} vector={h.vector_score:.4f} bm25={h.bm25_score:.4f} lexical={h.lexical_score:.4f} "
            f"doc={h.doc_id} chunk={h.chunk_index} type={h.chunk_type}{loc}{section}{routes}{refs}\n"
            f"{h.expanded_text or h.text}\n"
        )
    return "\n".join(lines)


def warmup_retrieval_runtime(cfg: AppConfig) -> dict[str, object]:
    """Best-effort warmup with a bounded, queryable diagnostic result."""

    started_at = datetime.now(timezone.utc).isoformat()
    checks: dict[str, dict[str, object]] = {}

    def record(
        component: str,
        status: str,
        *,
        required: bool,
        safe_message: str,
        exc: Exception | None = None,
    ) -> None:
        checks[component] = {
            "component": component,
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error_code": f"{component.upper()}_WARMUP_FAILED" if exc is not None else None,
            "error_type": type(exc).__name__ if exc is not None else None,
            "safe_message": safe_message,
            "required": required,
        }
        if exc is not None:
            logger.error("Retrieval warmup component failed: component=%s error_type=%s", component, type(exc).__name__)

    try:
        cfg = resolve_active_bundle(cfg).cfg
        record("index_bundle", "ready", required=True, safe_message="Index generation resolved and verified.")
    except Exception as exc:
        record("index_bundle", "not_ready", required=True, safe_message="Active index generation is invalid.", exc=exc)

    try:
        get_embedder(cfg)
        record("embedding", "ready", required=True, safe_message="Embedding runtime initialized.")
    except Exception as exc:
        record(
            "embedding",
            "not_ready",
            required=True,
            safe_message="Embedding runtime initialization failed.",
            exc=exc,
        )

    try:
        db = DB.create(cfg)
        record("database", "ready", required=True, safe_message="Retrieval database connection initialized.")
    except Exception as exc:
        db = None
        record(
            "database",
            "not_ready",
            required=True,
            safe_message="Retrieval database initialization failed.",
            exc=exc,
        )

    try:
        fim = FaissIndexManager(cfg)
        meta = fim.read_meta()
        dim = int(meta.get("dim", 0) or 0)
        if dim > 0:
            fim.load_or_create(dim)
        record("faiss", "ready", required=True, safe_message="FAISS warmup check completed.")
    except Exception as exc:
        record(
            "faiss",
            "not_ready",
            required=True,
            safe_message="FAISS warmup failed.",
            exc=exc,
        )

    if cfg.bm25.enabled and db is not None:
        try:
            BM25IndexManager(cfg).load()
            record("bm25", "ready", required=False, safe_message="BM25 warmup completed.")
        except Exception as exc:
            record(
                "bm25",
                "unavailable",
                required=False,
                safe_message="Optional BM25 warmup failed.",
                exc=exc,
            )
    else:
        record("bm25", "disabled", required=False, safe_message="BM25 warmup is disabled or blocked.")

    required_failures = [
        name for name, check in checks.items() if check["required"] and check["status"] != "ready"
    ]
    optional_failures = [
        name
        for name, check in checks.items()
        if not check["required"] and check["status"] not in {"ready", "disabled"}
    ]
    status = "not_ready" if required_failures else "degraded" if optional_failures else "ready"
    first_failure = checks[required_failures[0]] if required_failures else None
    return {
        "component": "retrieval",
        "status": status,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "error_code": "RETRIEVAL_WARMUP_REQUIRED_FAILURE" if required_failures else None,
        "error_type": first_failure.get("error_type") if first_failure else None,
        "safe_message": "Retrieval warmup completed." if status == "ready" else "Retrieval warmup completed with failures.",
        "required": True,
        "checks": checks,
        "required_failures": required_failures,
        "optional_failures": optional_failures,
    }


def retrieve_with_plan(
    cfg: AppConfig,
    question: str,
    *,
    topk: int | None = None,
    neighbor_window: int | None = None,
) -> Tuple[List[Hit], int, QueryPlan]:
    bundle = resolve_active_bundle(cfg)
    cfg = bundle.cfg
    topk = topk or cfg.retrieval.topk_default
    neighbor_window = cfg.retrieval.neighbor_window if neighbor_window is None else neighbor_window
    db = DB.create(cfg)
    plan = analyze_query(cfg, question)
    plan.notes.append(f"index_generation={bundle.version}")
    t0 = time.time()

    vector_hits: list[Hit] = []
    faiss_topn = 0
    for idx, q in enumerate(plan.vector_queries()):
        if idx == 0:
            route = "vector:original"
        elif q in {focus_retrieval_query(item) for item in plan.rewritten_queries}:
            route = "vector:rewrite"
        else:
            route = "vector:subquery"
        route_hits, route_topn, db, _dim = retrieve_vector_candidates(cfg, q, topk=topk, db=db, route=route, bundle=bundle)
        vector_hits.extend(route_hits)
        faiss_topn = max(faiss_topn, route_topn)

    bm25_groups: list[tuple[str, Sequence[tuple[int, float]]]] = []
    for idx, q in enumerate(plan.bm25_queries()):
        route = "bm25:original" if idx == 0 else "bm25:keyword"
        bm25_hits, db = retrieve_bm25_candidates(cfg, q, db=db, bundle=bundle)
        bm25_groups.append((route, bm25_hits))

    exact_hits, db = retrieve_exact_reference_candidates(cfg, plan, db=db, allowed_chunk_ids=bundle.mapping_chunk_ids)

    merged = _merge_candidates(db, vector_hits, bm25_groups, exact_hits=exact_hits)
    hits = rerank_candidates(
        cfg,
        question=plan.original_query,
        candidates=merged,
        topk=topk,
        db=db,
        neighbor_window=neighbor_window,
        plan=plan,
    )

    latency_ms = int((time.time() - t0) * 1000)
    try:
        db.log_retrieval(
            query_text=question,
            topk=topk,
            faiss_topn=faiss_topn,
            latency_ms=latency_ms,
            model_name=cfg.embedding.model_name,
            hit_vector_pos=[h.vector_pos for h in hits if h.vector_pos is not None],
            hit_chunk_ids=[h.chunk_id for h in hits],
        )
    except Exception:
        pass
    return hits, latency_ms, plan


def retrieve(cfg: AppConfig, question: str, *, topk: int | None = None, neighbor_window: int | None = None) -> Tuple[List[Hit], int]:
    hits, latency_ms, _plan = retrieve_with_plan(cfg, question, topk=topk, neighbor_window=neighbor_window)
    return hits, latency_ms
