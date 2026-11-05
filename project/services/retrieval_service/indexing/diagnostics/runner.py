from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Protocol
import pickle

import numpy as np

from services.retrieval_service.bm25_index import bm25_tokenize, load_bm25_payload
from services.retrieval_service.config import AppConfig
from services.retrieval_service.embed_index import build_embeddings
from ..artifact_io import read_faiss_index
from services.retrieval_service.query_analyzer import analyze_query
from services.retrieval_service.retriever import (
    Hit,
    _merge_candidates,
    _normalize_scores,
    rerank_candidates,
    retrieve_exact_reference_candidates,
)


class ChunkStore(Protocol):
    def get_chunk_full_by_id(self, chunk_id: int): ...

    def list_neighbor_chunks(self, *, doc_id: int, chunk_index: int, window: int = 1): ...

    def fetchall(self, sql: str, params=None): ...


def _rank_map(items: list[int]) -> dict[int, int]:
    output: dict[int, int] = {}
    for rank, item in enumerate(items, start=1):
        output.setdefault(int(item), rank)
    return output


def _first_rank(results: list[dict[str, Any]], acceptable: set[int]) -> int | None:
    return next(
        (index for index, item in enumerate(results, start=1) if int(item["chunk_id"]) in acceptable),
        None,
    )


class DiagnosticRuntime:
    """Runs production-equivalent retrieval against an explicit index bundle.

    The class never chooses production paths and never logs retrieval. A caller
    supplies a SELECT-only chunk store for real diagnostics.
    """

    def __init__(
        self,
        cfg: AppConfig,
        bundle: dict[str, Any],
        *,
        store: ChunkStore,
        catalog: dict[int, dict[str, Any]],
        embed_query: Callable[[str], np.ndarray] | None = None,
    ) -> None:
        import faiss  # type: ignore
        from rank_bm25 import BM25Okapi  # type: ignore

        self.cfg = cfg
        self.bundle = dict(bundle)
        self.store = store
        self.catalog = {int(key): dict(value) for key, value in catalog.items()}
        self.embed_query = embed_query or (
            lambda query: build_embeddings(self.cfg, [query], strip_meta=False)
        )
        self.index = read_faiss_index(bundle["faiss_path"])
        self.mapping = [int(item) for item in bundle.get("mapping_chunk_ids") or []]
        payload, self.bm25_tokenizer_version = load_bm25_payload(bundle["bm25_path"], bundle.get("bm25_meta_path"), expected_version=bundle.get("bm25_tokenizer_version"))
        self.bm25_ids = [int(item) for item in payload.get("chunk_ids", [])]
        self.bm25_tokens = list(payload.get("tokenized_corpus", []))
        self.bm25 = BM25Okapi(self.bm25_tokens, k1=cfg.bm25.k1, b=cfg.bm25.b)
        self.invalid_mapping_count = max(0, int(self.index.ntotal) - len(self.mapping))

    def _hit(
        self,
        chunk_id: int,
        *,
        vector_score: float = 0.0,
        bm25_score: float = 0.0,
        vector_pos: int | None = None,
        route: str,
    ) -> Hit | None:
        row = self.store.get_chunk_full_by_id(int(chunk_id))
        if not row:
            self.invalid_mapping_count += 1
            return None
        _, doc_id, chunk_idx, ps, pe, chunk_type, text, token_len, section_path, _hash, meta = row
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
            vector_pos=vector_pos,
            retrieval_routes=[route],
            meta_json=str(meta) if meta else None,
        )

    def _vector_candidates(self, plan, top_k: int) -> tuple[list[Hit], dict[int, int], float]:
        started = perf_counter()
        hits: list[Hit] = []
        best_ranks: dict[int, int] = {}
        topn = min(
            int(self.index.ntotal),
            max(self.cfg.retrieval.faiss_topn_base, top_k * self.cfg.retrieval.faiss_topn_multiplier),
        )
        for route_index, route_query in enumerate(plan.vector_queries()):
            route = "vector:original" if route_index == 0 else "vector:rewrite"
            vector = np.asarray(self.embed_query(route_query), dtype="float32")
            scores, positions = self.index.search(vector, topn)
            for rank, (score, position_value) in enumerate(
                zip(scores[0].tolist(), positions[0].tolist()), start=1
            ):
                position = int(position_value)
                if position < 0 or position >= len(self.mapping):
                    if position >= 0:
                        self.invalid_mapping_count += 1
                    continue
                chunk_id = int(self.mapping[position])
                best_ranks[chunk_id] = min(rank, best_ranks.get(chunk_id, rank))
                hit = self._hit(
                    chunk_id,
                    vector_score=float(score),
                    vector_pos=position,
                    route=route,
                )
                if hit:
                    hits.append(hit)
        return hits, best_ranks, (perf_counter() - started) * 1000.0

    def _bm25_candidates(self, plan) -> tuple[list[tuple[str, list[tuple[int, float]]]], dict[int, int], float]:
        started = perf_counter()
        groups: list[tuple[str, list[tuple[int, float]]]] = []
        best_ranks: dict[int, int] = {}
        for route_index, route_query in enumerate(plan.bm25_queries()):
            route = "bm25:original" if route_index == 0 else "bm25:keyword"
            tokens = bm25_tokenize(route_query, version=self.bm25_tokenizer_version)
            ranked_hits: list[tuple[int, float]] = []
            if tokens:
                scores = self.bm25.get_scores(tokens)
                ranked = sorted(
                    enumerate(scores.tolist()), key=lambda item: item[1], reverse=True
                )
                for rank, (position, score) in enumerate(ranked[: self.cfg.bm25.topn], start=1):
                    if float(score) <= 0:
                        continue
                    chunk_id = int(self.bm25_ids[position])
                    ranked_hits.append((chunk_id, float(score)))
                    best_ranks[chunk_id] = min(rank, best_ranks.get(chunk_id, rank))
            groups.append((route, ranked_hits))
        return groups, best_ranks, (perf_counter() - started) * 1000.0

    def _format_result(
        self,
        hit: Hit,
        *,
        rank: int,
        mode: str,
        vector_rank: dict[int, int],
        bm25_rank: dict[int, int],
        vector_norm: dict[int, float],
        bm25_norm: dict[int, float],
        expected_chunks: set[int],
        acceptable_chunks: set[int],
        expected_documents: set[int],
        acceptable_documents: set[int],
    ) -> dict[str, Any]:
        meta = self.catalog.get(int(hit.chunk_id), {})
        raw_score: float | None
        normalized_score: float | None
        if mode == "faiss":
            raw_score = float(hit.vector_score)
            normalized_score = vector_norm.get(int(hit.chunk_id))
        elif mode == "bm25":
            raw_score = float(hit.bm25_score)
            normalized_score = bm25_norm.get(int(hit.chunk_id))
        else:
            raw_score = None
            normalized_score = None
        preview = " ".join(str(meta.get("text") or hit.text or "").split())[:280]
        return {
            "rank": rank,
            "chunk_id": int(hit.chunk_id),
            "document_id": int(hit.doc_id),
            "source_asset_id": meta.get("source_asset_id"),
            "document_title": meta.get("document_title"),
            "source_name": meta.get("source_name"),
            "section_title": meta.get("section_title") or hit.section_path,
            "chunk_text_preview": preview,
            "content_length": len(str(meta.get("text") or hit.text or "")),
            "raw_score": round(raw_score, 8) if raw_score is not None else None,
            "normalized_score": round(float(normalized_score), 8) if normalized_score is not None else None,
            "hybrid_score": round(float(hit.score), 8) if mode == "hybrid" else None,
            "final_score": round(float(hit.score), 8),
            "vector_score": round(float(hit.vector_score), 8),
            "bm25_score": round(float(hit.bm25_score), 8),
            "lexical_score": round(float(hit.lexical_score), 8),
            "faiss_rank": vector_rank.get(int(hit.chunk_id)),
            "bm25_rank": bm25_rank.get(int(hit.chunk_id)),
            "retrieval_routes": list(hit.retrieval_routes),
            "is_expected_chunk": int(hit.chunk_id) in expected_chunks,
            "is_acceptable_chunk": int(hit.chunk_id) in acceptable_chunks,
            "is_expected_document": int(hit.doc_id) in expected_documents,
            "is_acceptable_document": int(hit.doc_id) in acceptable_documents,
            "heuristic_noise_flags": [],
        }

    def _run_mode(
        self,
        *,
        mode: str,
        plan,
        vector_hits: list[Hit],
        bm25_groups: list[tuple[str, list[tuple[int, float]]]],
        exact_hits: list[Hit],
        vector_rank: dict[int, int],
        bm25_rank: dict[int, int],
        top_k: int,
        base_latency_ms: float,
        case: dict[str, Any],
    ) -> dict[str, Any]:
        started = perf_counter()
        selected_vectors = deepcopy(vector_hits) if mode in {"faiss", "hybrid"} else []
        selected_bm25 = deepcopy(bm25_groups) if mode in {"bm25", "hybrid"} else []
        selected_exact = deepcopy(exact_hits) if mode == "hybrid" else []
        merged = _merge_candidates(
            self.store,
            selected_vectors,
            selected_bm25,
            exact_hits=selected_exact,
        )
        vector_values = _normalize_scores([hit.vector_score for hit in merged])
        bm25_values = _normalize_scores([hit.bm25_score for hit in merged])
        vector_norm = {int(hit.chunk_id): value for hit, value in zip(merged, vector_values)}
        bm25_norm = {int(hit.chunk_id): value for hit, value in zip(merged, bm25_values)}
        hits = rerank_candidates(
            self.cfg,
            question=plan.original_query,
            candidates=merged,
            topk=top_k,
            db=self.store,
            neighbor_window=self.cfg.retrieval.neighbor_window,
            plan=plan,
        )
        expected_chunks = {int(item) for item in case.get("expected_chunk_ids") or []}
        acceptable_chunks = expected_chunks | {
            int(item) for item in case.get("acceptable_chunk_ids") or []
        }
        expected_documents = {int(item) for item in case.get("expected_document_ids") or []}
        acceptable_documents = expected_documents | {
            int(item) for item in case.get("acceptable_document_ids") or []
        }
        results = [
            self._format_result(
                hit,
                rank=rank,
                mode=mode,
                vector_rank=vector_rank,
                bm25_rank=bm25_rank,
                vector_norm=vector_norm,
                bm25_norm=bm25_norm,
                expected_chunks=expected_chunks,
                acceptable_chunks=acceptable_chunks,
                expected_documents=expected_documents,
                acceptable_documents=acceptable_documents,
            )
            for rank, hit in enumerate(hits, start=1)
        ]
        first_rank = _first_rank(results, acceptable_chunks)
        first_document_rank = next(
            (
                index
                for index, item in enumerate(results, start=1)
                if int(item["document_id"]) in acceptable_documents
            ),
            None,
        )
        scores = [float(item["final_score"]) for item in results]
        expected_result = next(
            (item for item in results if int(item["chunk_id"]) in acceptable_chunks), None
        )
        elapsed = base_latency_ms + (perf_counter() - started) * 1000.0
        return {
            "mode": mode,
            "results": results,
            "candidate_pool_count": len(merged),
            "first_relevant_rank": first_rank,
            "first_relevant_document_rank": first_document_rank,
            "reciprocal_rank": round(1.0 / first_rank, 8) if first_rank else 0.0,
            **{f"hit_at_{k}": bool(first_rank and first_rank <= k) for k in (1, 3, 5, 10)},
            **{
                f"document_hit_at_{k}": bool(first_document_rank and first_document_rank <= k)
                for k in (1, 3, 5, 10)
            },
            "top_result_score": scores[0] if scores else None,
            "top1_top2_margin": round(scores[0] - scores[1], 8) if len(scores) > 1 else None,
            "expected_result_score": expected_result.get("final_score") if expected_result else None,
            "latency_ms": round(elapsed, 4),
        }

    def diagnose_case(self, case: dict[str, Any], *, top_k: int = 10) -> dict[str, Any]:
        np.random.seed(0)
        plan = analyze_query(self.cfg, str(case.get("query") or ""))
        invalid_before = self.invalid_mapping_count
        vector_hits, vector_rank, vector_ms = self._vector_candidates(plan, top_k)
        bm25_groups, bm25_rank, bm25_ms = self._bm25_candidates(plan)
        exact_started = perf_counter()
        exact_hits, _ = retrieve_exact_reference_candidates(
            self.cfg, plan, db=self.store
        )
        exact_ms = (perf_counter() - exact_started) * 1000.0
        modes = {
            "faiss": self._run_mode(
                mode="faiss",
                plan=plan,
                vector_hits=vector_hits,
                bm25_groups=bm25_groups,
                exact_hits=exact_hits,
                vector_rank=vector_rank,
                bm25_rank=bm25_rank,
                top_k=top_k,
                base_latency_ms=vector_ms,
                case=case,
            ),
            "bm25": self._run_mode(
                mode="bm25",
                plan=plan,
                vector_hits=vector_hits,
                bm25_groups=bm25_groups,
                exact_hits=exact_hits,
                vector_rank=vector_rank,
                bm25_rank=bm25_rank,
                top_k=top_k,
                base_latency_ms=bm25_ms,
                case=case,
            ),
            "hybrid": self._run_mode(
                mode="hybrid",
                plan=plan,
                vector_hits=vector_hits,
                bm25_groups=bm25_groups,
                exact_hits=exact_hits,
                vector_rank=vector_rank,
                bm25_rank=bm25_rank,
                top_k=top_k,
                base_latency_ms=vector_ms + bm25_ms + exact_ms,
                case=case,
            ),
        }
        acceptable = {int(item) for item in case.get("expected_chunk_ids") or []} | {
            int(item) for item in case.get("acceptable_chunk_ids") or []
        }
        return {
            "case_id": case.get("case_id"),
            "query": case.get("query"),
            "category": case.get("category"),
            "corpus_scope": case.get("corpus_scope"),
            "answerable": bool(case.get("answerable", True)),
            "expected_chunk_ids": list(case.get("expected_chunk_ids") or []),
            "acceptable_chunk_ids": list(case.get("acceptable_chunk_ids") or []),
            "expected_document_ids": list(case.get("expected_document_ids") or []),
            "must_not_return_document_ids": list(case.get("must_not_return_document_ids") or []),
            "query_plan": {
                "intent": plan.intent,
                "vector_query_count": len(plan.vector_queries()),
                "bm25_query_count": len(plan.bm25_queries()),
            },
            "modes": modes,
            "candidate_presence": {
                "faiss_top_10": any(vector_rank.get(item, 10**9) <= 10 for item in acceptable),
                "bm25_top_10": any(bm25_rank.get(item, 10**9) <= 10 for item in acceptable),
                "hybrid_top_10": bool(modes["hybrid"]["hit_at_10"]),
            },
            "invalid_mapping_count": self.invalid_mapping_count - invalid_before,
            "deterministic_seed": 0,
        }
