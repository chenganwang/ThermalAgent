from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import json
import pickle
import re
import time

import numpy as np

from services.ingest_service.external_ingestion import connect_mysql
from services.retrieval_service.bm25_index import bm25_tokenize, load_bm25_payload
from services.retrieval_service.config import AppConfig
from services.retrieval_service.db import DB
from services.retrieval_service.embed_index import build_embeddings
from services.retrieval_service.query_analyzer import analyze_query
from services.retrieval_service.retriever import (
    Hit,
    _merge_candidates,
    rerank_candidates,
    retrieve_exact_reference_candidates,
)

from .explicit_bundles import build_old_bundle, build_candidate_bundle
from .artifact_io import read_faiss_index


REQUIRED_HOLDOUT_FIELDS = {
    "case_id", "query", "category", "corpus_scope", "expected_document_ids",
    "expected_source_filenames", "relevant_chunk_ids", "acceptable_chunk_ids",
    "forbidden_document_ids", "expected_topic", "query_style", "notes",
}


def load_holdout(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata"), dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("holdout must contain metadata object and cases list")
    for index, case in enumerate(payload["cases"]):
        if not isinstance(case, dict):
            raise ValueError(f"holdout case {index} must be an object")
        missing = REQUIRED_HOLDOUT_FIELDS - set(case)
        if missing:
            raise ValueError(f"holdout case {case.get('case_id', index)} missing fields: {sorted(missing)}")
    return payload


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def validate_holdout(
    cfg: AppConfig,
    dataset: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    cases = [dict(case) for case in dataset.get("cases") or []]
    metadata = dict(dataset.get("metadata") or {})
    manifest_by_id = {int(row["chunk_id"]): dict(row) for row in manifest.get("rows") or []}
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, title, source, local_path FROM documents ORDER BY id")
        documents = {int(row["id"]): dict(row) for row in (cursor.fetchall() or [])}
    finally:
        connection.close()

    ids = [str(case.get("case_id") or "") for case in cases]
    duplicate_case_ids = sorted({item for item in ids if ids.count(item) > 1})
    missing_chunk_ids: set[int] = set()
    document_mismatch_cases: list[str] = []
    source_filename_mismatch_cases: list[str] = []
    full_title_leakage_cases: list[str] = []
    query_contains_chunk_id_cases: list[str] = []

    for case in cases:
        case_id = str(case.get("case_id"))
        expected_docs = {int(item) for item in case.get("expected_document_ids") or []}
        expected_files = {str(item) for item in case.get("expected_source_filenames") or []}
        chunk_ids = {
            int(item)
            for item in list(case.get("relevant_chunk_ids") or []) + list(case.get("acceptable_chunk_ids") or [])
        }
        missing = chunk_ids - set(manifest_by_id)
        missing_chunk_ids.update(missing)
        existing_rows = [manifest_by_id[item] for item in chunk_ids if item in manifest_by_id]
        relevant_rows = [manifest_by_id[int(item)] for item in case.get("relevant_chunk_ids") or [] if int(item) in manifest_by_id]
        if relevant_rows and not all(int(row["document_id"]) in expected_docs for row in relevant_rows):
            document_mismatch_cases.append(case_id)
        if relevant_rows and not all(str(row.get("source_filename") or "") in expected_files for row in relevant_rows):
            source_filename_mismatch_cases.append(case_id)

        normalized_query = _norm(case.get("query"))
        for document_id in expected_docs:
            title = _norm(documents.get(document_id, {}).get("title"))
            if title and len(title) >= 4 and title in normalized_query:
                full_title_leakage_cases.append(case_id)
                break
        if any(str(chunk_id) in str(case.get("query") or "") for chunk_id in chunk_ids):
            query_contains_chunk_id_cases.append(case_id)

    errors = []
    if len(cases) != 30:
        errors.append("case_count_not_30")
    if duplicate_case_ids:
        errors.append("duplicate_case_ids")
    if missing_chunk_ids:
        errors.append("missing_chunk_ids")
    if document_mismatch_cases:
        errors.append("document_mismatch")
    if source_filename_mismatch_cases:
        errors.append("source_filename_mismatch")
    if full_title_leakage_cases:
        errors.append("full_title_leakage")
    if query_contains_chunk_id_cases:
        errors.append("query_contains_chunk_id")
    return {
        "passed": not errors,
        "errors": errors,
        "case_count": len(cases),
        "duplicate_case_ids": duplicate_case_ids,
        "missing_chunk_ids": sorted(missing_chunk_ids),
        "document_mismatch_cases": document_mismatch_cases,
        "source_filename_mismatch_cases": source_filename_mismatch_cases,
        "full_title_leakage_cases": full_title_leakage_cases,
        "query_contains_chunk_id_cases": query_contains_chunk_id_cases,
        "builder_type": metadata.get("builder_type"),
        "human_validated": bool(metadata.get("human_validated")),
        "source_chunks_checked": bool(metadata.get("source_chunks_checked")),
        "external_model_used": bool(metadata.get("external_model_used")),
        "manifest_count": len(manifest_by_id),
    }



class _BundleRuntime:
    def __init__(self, cfg: AppConfig, bundle: dict[str, Any], *, embed_query: Callable[[str], np.ndarray] | None = None) -> None:
        import faiss  # type: ignore
        from rank_bm25 import BM25Okapi  # type: ignore
        from .diagnostics.read_only_store import SelectOnlyChunkStore

        self.cfg = cfg
        self.embed_query = embed_query or (lambda query: build_embeddings(cfg, [query], strip_meta=False))
        self.bundle = bundle
        self.index = read_faiss_index(bundle["faiss_path"])
        self.mapping = [int(item) for item in bundle.get("mapping_chunk_ids") or []]
        payload, self.bm25_tokenizer_version = load_bm25_payload(bundle["bm25_path"], bundle.get("bm25_meta_path"), expected_version=bundle.get("bm25_tokenizer_version"))
        self.bm25_ids = [int(item) for item in payload.get("chunk_ids", [])]
        self.bm25_tokens = list(payload.get("tokenized_corpus", []))
        self.bm25 = BM25Okapi(self.bm25_tokens, k1=cfg.bm25.k1, b=cfg.bm25.b)
        self.db = SelectOnlyChunkStore(cfg)
        self.db.load_chunk_catalog()
        self.invalid_mapping_count = max(0, int(self.index.ntotal) - len(self.mapping))

    def _hit(self, chunk_id: int, *, vector_score: float = 0.0, bm25_score: float = 0.0, position: int | None = None, route: str) -> Hit | None:
        row = self.db.get_chunk_full_by_id(int(chunk_id))
        if not row:
            self.invalid_mapping_count += 1
            return None
        _, doc_id, chunk_idx, ps, pe, chunk_type, text, token_len, section_path, _content_hash, meta_json = row
        return Hit(
            score=float(vector_score),
            vector_score=float(vector_score),
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
            vector_pos=position,
            retrieval_routes=[route],
            meta_json=str(meta_json) if meta_json else None,
        )

    def vector_hits(self, query: str, *, top_k: int, route: str) -> list[Hit]:
        vectors = np.asarray(self.embed_query(query), dtype="float32")
        topn = min(int(self.index.ntotal), max(self.cfg.retrieval.faiss_topn_base, top_k * self.cfg.retrieval.faiss_topn_multiplier))
        scores, positions = self.index.search(vectors, topn)
        hits: list[Hit] = []
        for score, position in zip(scores[0].tolist(), positions[0].tolist()):
            position = int(position)
            if position < 0 or position >= len(self.mapping):
                if position >= 0:
                    self.invalid_mapping_count += 1
                continue
            hit = self._hit(self.mapping[position], vector_score=float(score), position=position, route=route)
            if hit:
                hits.append(hit)
        return hits

    def bm25_hits(self, query: str, *, topn: int) -> list[tuple[int, float]]:
        tokens = bm25_tokenize(query, version=self.bm25_tokenizer_version)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores.tolist()), key=lambda item: item[1], reverse=True)
        return [
            (self.bm25_ids[position], float(score))
            for position, score in ranked[:topn]
            if float(score) > 0
        ]

    def search(self, query: str, *, mode: str, top_k: int = 5) -> tuple[list[Hit], float]:
        started = time.perf_counter()
        plan = analyze_query(self.cfg, query)
        vector_hits: list[Hit] = []
        bm25_groups: list[tuple[str, list[tuple[int, float]]]] = []
        if mode in {"faiss", "hybrid"}:
            for index, route_query in enumerate(plan.vector_queries()):
                route = "vector:original" if index == 0 else "vector:rewrite"
                vector_hits.extend(self.vector_hits(route_query, top_k=top_k, route=route))
        if mode in {"bm25", "hybrid"}:
            for index, route_query in enumerate(plan.bm25_queries()):
                route = "bm25:original" if index == 0 else "bm25:keyword"
                bm25_groups.append((route, self.bm25_hits(route_query, topn=self.cfg.bm25.topn)))
        exact_hits: list[Hit] = []
        if mode == "hybrid":
            exact_hits, _ = retrieve_exact_reference_candidates(self.cfg, plan, db=self.db)
        merged = _merge_candidates(self.db, vector_hits, bm25_groups, exact_hits=exact_hits)
        hits = rerank_candidates(
            self.cfg,
            question=plan.original_query,
            candidates=merged,
            topk=top_k,
            db=self.db,
            neighbor_window=self.cfg.retrieval.neighbor_window,
            plan=plan,
        )
        return hits, (time.perf_counter() - started) * 1000.0


def _mean(values: list[float]) -> float:
    return round(float(sum(values) / len(values)), 4) if values else 0.0


def _scope_recall(rows: list[dict[str, Any]], scope: str, key: str) -> float:
    selected = [row for row in rows if row.get("corpus_scope") == scope]
    return _mean([float(row.get(key) or 0.0) for row in selected])


def _evaluate_mode(runtime: _BundleRuntime, cases: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    invalid_before = runtime.invalid_mapping_count
    for case in cases:
        hits, latency = runtime.search(str(case.get("query") or ""), mode=mode, top_k=5)
        latencies.append(latency)
        hit_ids = [int(hit.chunk_id) for hit in hits]
        hit_docs = [int(hit.doc_id) for hit in hits]
        relevant = {int(item) for item in case.get("relevant_chunk_ids") or []}
        acceptable = relevant | {int(item) for item in case.get("acceptable_chunk_ids") or []}
        expected_docs = {int(item) for item in case.get("expected_document_ids") or []}
        forbidden_docs = {int(item) for item in case.get("forbidden_document_ids") or []}

        def recall_at(k: int) -> float:
            return len(relevant & set(hit_ids[:k])) / len(relevant) if relevant else 1.0

        def precision_at(k: int) -> float:
            return len(acceptable & set(hit_ids[:k])) / float(k)

        first_rank = next((index + 1 for index, chunk_id in enumerate(hit_ids) if chunk_id in acceptable), None)
        rows.append(
            {
                "case_id": case.get("case_id"),
                "corpus_scope": case.get("corpus_scope"),
                "query": case.get("query"),
                "hit_chunk_ids": hit_ids,
                "hit_document_ids": hit_docs,
                "recall_at_1": recall_at(1),
                "recall_at_3": recall_at(3),
                "recall_at_5": recall_at(5),
                "precision_at_1": precision_at(1),
                "precision_at_3": precision_at(3),
                "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
                "source_document_accuracy_at_1": float(bool(set(hit_docs[:1]) & expected_docs)),
                "source_document_accuracy_at_3": float(bool(set(hit_docs[:3]) & expected_docs)),
                "has_relevant_at_3": bool(set(hit_ids[:3]) & acceptable),
                "negative_false_positive": bool(
                    case.get("corpus_scope") == "confusion_negative"
                    and set(hit_docs[:3]) & forbidden_docs
                ),
                "empty_result": not hit_ids,
                "latency_ms": round(latency, 4),
            }
        )
    negative_rows = [row for row in rows if row["corpus_scope"] == "confusion_negative"]
    provenance_hits = sum(len(row["hit_chunk_ids"]) for row in rows)
    invalid_delta = runtime.invalid_mapping_count - invalid_before
    return {
        "case_count": len(rows),
        "recall_at_1": _mean([row["recall_at_1"] for row in rows]),
        "recall_at_3": _mean([row["recall_at_3"] for row in rows]),
        "recall_at_5": _mean([row["recall_at_5"] for row in rows]),
        "precision_at_1": _mean([row["precision_at_1"] for row in rows]),
        "precision_at_3": _mean([row["precision_at_3"] for row in rows]),
        "mrr": _mean([row["reciprocal_rank"] for row in rows]),
        "source_document_accuracy_at_1": _mean([row["source_document_accuracy_at_1"] for row in rows]),
        "source_document_accuracy_at_3": _mean([row["source_document_accuracy_at_3"] for row in rows]),
        "provenance_accuracy": round((provenance_hits - invalid_delta) / provenance_hits, 4) if provenance_hits else 1.0,
        "old_query_recall_at_3": _scope_recall(rows, "legacy_protection", "recall_at_3"),
        "new_source_recall_at_3": _scope_recall(rows, "new_external_source", "recall_at_3"),
        "new_source_hit_rate": _mean([
            float(row["has_relevant_at_3"])
            for row in rows
            if row["corpus_scope"] == "new_external_source"
        ]),
        "negative_case_false_positive_rate": _mean([
            float(row["negative_false_positive"]) for row in negative_rows
        ]),
        "average_latency_ms": _mean(latencies),
        "p95_latency_ms": round(float(np.percentile(latencies, 95)), 4) if latencies else 0.0,
        "empty_result_rate": _mean([float(row["empty_result"]) for row in rows]),
        "invalid_chunk_mapping_count": invalid_delta,
        "rows": rows,
    }


def evaluate_holdout(
    cfg: AppConfig,
    cases: list[dict[str, Any]],
    bundle: dict[str, Any],
    *,
    modes: tuple[str, ...] = ("faiss", "bm25", "hybrid"),
    embed_query: Callable[[str], np.ndarray] | None = None,
) -> dict[str, Any]:
    runtime = _BundleRuntime(cfg, bundle, embed_query=embed_query)
    try:
        mode_results = {mode: _evaluate_mode(runtime, cases, mode) for mode in modes}
    finally:
        runtime.db.close()
    return {
        "bundle_name": bundle.get("name"),
        "index_version": bundle.get("version"),
        "case_count": len(cases),
        "modes": mode_results,
        "sample_limited": True,
        "human_validated": False,
        "production_ready": False,
        "database_written": False,
        "query_embeddings_supplied": embed_query is not None,
        "knowledge_units_included": bool(bundle.get("knowledge_units_included")),
    }
