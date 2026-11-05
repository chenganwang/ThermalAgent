"""Read-only ablations over explicit VNext candidates, never active indexes.

Original hybrid delegates to the existing production query plan/merge/rerank.
Pure BM25/dense deliberately omit its lexical/type reranker so the ablations
measure the named channels. RRF and MMR are independently implemented formulas.
"""
from __future__ import annotations

from time import perf_counter
from typing import Callable

import numpy as np

from ..bm25_tokenizer import bm25_tokenize
from ..query_analyzer import analyze_query
from ..retriever import retrieve_exact_reference_candidates
from .diagnostics.runner import DiagnosticRuntime
from .vnext_artifacts import load_candidate, memory_usage


def reciprocal_rank_fusion(rankings: list[list[str]], *, rank_constant: int = 60) -> dict[str, float]:
    if type(rank_constant) is not int or rank_constant < 1:
        raise ValueError('RRF rank_constant must be a positive integer')
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen = set()
        for rank, identity in enumerate(ranking, 1):
            if identity in seen:
                continue
            seen.add(identity)
            scores[identity] = scores.get(identity, 0.) + 1. / (rank_constant + rank)
    return scores


class _MemoryChunkStore:
    """The existing retrieval read interface over an immutable local snapshot."""
    def __init__(self, chunks: list[dict], selected: set[int]):
        self.rows: dict[int, tuple] = {}
        self.catalog: dict[int, dict] = {}
        doc_ids = {name: i + 1 for i, name in enumerate(sorted({r['source_id'] for r in chunks}))}
        counters: dict[str, int] = {}
        for i, chunk in enumerate(chunks):
            source = chunk['source_id']
            ordinal = counters.get(source, 0)
            counters[source] = ordinal + 1
            if i not in selected:
                continue
            section = chunk['section_path']
            section = ' / '.join(section) if isinstance(section, list) else str(section or '')
            kind = chunk.get('chunk_type') or ('table' if chunk.get('table_context') else 'text')
            self.rows[i + 1] = (i + 1, doc_ids[source], ordinal, chunk['page_start'], chunk['page_end'],
                                kind, chunk['text'], len(chunk['text']), section, chunk['content_sha256'], None)
            self.catalog[i + 1] = {'text': chunk['text'], 'document_title': chunk.get('title', source),
                                    'source_name': source, 'section_title': section}

    def get_chunk_full_by_id(self, chunk_id: int):
        return self.rows.get(chunk_id)

    def list_neighbor_chunks(self, *, doc_id: int, chunk_index: int, window: int = 1):
        return [row for row in self.rows.values() if row[1] == doc_id and abs(row[2] - chunk_index) <= window]

    def fetchall(self, sql: str, params=None):
        expected = ('SELECT id, doc_id, chunk_index, page_start, page_end, chunk_type, text, token_len, section_path, content_hash, meta_json '
                    'FROM chunks WHERE is_active=1 ORDER BY id')
        if ' '.join(sql.split()) != expected or params:
            raise ValueError('memory experiment store permits only the production exact-reference SELECT')
        return list(self.rows.values())


class _SafeDiagnosticRuntime(DiagnosticRuntime):
    def __init__(self, artifact: dict, cfg, selected: list[int], embed_query):
        # Reuse production-equivalent methods without its legacy pickle loader.
        import faiss
        from rank_bm25 import BM25Okapi
        self.cfg = cfg
        self.store = _MemoryChunkStore(artifact['chunks'], set(selected))
        self.catalog = self.store.catalog
        self.embed_query = embed_query
        self.index = faiss.IndexFlatIP(artifact['manifest']['dimension'])
        self.index.add(artifact['vectors'][selected])
        self.mapping = [i + 1 for i in selected]
        self.bm25_ids = self.mapping[:]
        self.bm25_tokens = [artifact['bm25']['tokens'][i] for i in selected]
        self.bm25 = BM25Okapi(self.bm25_tokens, k1=cfg.bm25.k1, b=cfg.bm25.b) if any(self.bm25_tokens) else _EmptyLexicalCorpus(len(selected))
        self.bm25_tokenizer_version = artifact['manifest']['tokenizer_version']
        self.invalid_mapping_count = 0
        self.bundle = {'source': 'vnext_safe_local_artifacts'}

    def hybrid(self, query: str, top_k: int) -> dict:
        """Execute only the production hybrid, not its diagnostic ablations."""
        plan = analyze_query(self.cfg, query)
        vector_hits, vector_rank, vector_ms = self._vector_candidates(plan, top_k)
        bm25_groups, bm25_rank, bm25_ms = self._bm25_candidates(plan)
        started = perf_counter()
        exact_hits, _ = retrieve_exact_reference_candidates(self.cfg, plan, db=self.store)
        return self._run_mode(mode='hybrid', plan=plan, vector_hits=vector_hits,
                              bm25_groups=bm25_groups, exact_hits=exact_hits, vector_rank=vector_rank,
                              bm25_rank=bm25_rank, top_k=top_k,
                              base_latency_ms=vector_ms+bm25_ms+(perf_counter()-started)*1000, case={})


class _EmptyLexicalCorpus:
    """Explicitly no sparse evidence after filtering, without a fake token."""
    def __init__(self, size: int):
        self.size = size

    def get_scores(self, tokens):
        return np.zeros(self.size, dtype=np.float64)


def _selected(chunks: list[dict], filters: dict | None) -> list[int]:
    filters = filters or {}
    if set(filters) - {'review_status', 'source_ids', 'exclude_quality_flags'}:
        raise ValueError('unknown metadata filter; do not silently ignore restrictions')
    for values in filters.values():
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError('metadata filter values must be explicit string arrays')
    selected = []
    for i, row in enumerate(chunks):
        if row['review_status'] == 'rejected':
            continue
        if 'review_status' in filters and row['review_status'] not in filters['review_status']:
            continue
        if 'source_ids' in filters and row['source_id'] not in filters['source_ids']:
            continue
        if set(row.get('quality_flags') or []) & set(filters.get('exclude_quality_flags') or []):
            continue
        selected.append(i)
    return selected


class CandidateRuntime:
    def __init__(self, path, *, cfg, embed_query: Callable[[str], np.ndarray]):
        from rank_bm25 import BM25Okapi
        self.artifact = load_candidate(path)
        self.cfg = cfg
        self.chunks = self.artifact['chunks']
        self.vectors = self.artifact['vectors']
        self.embed_query = embed_query
        self.bm25 = BM25Okapi(self.artifact['bm25']['tokens'], k1=self.artifact['bm25']['k1'], b=self.artifact['bm25']['b'])
        self._query_cache: dict[str, np.ndarray] = {}
        self.embedding_calls = 0

    def _query(self, query: str) -> np.ndarray:
        if query not in self._query_cache:
            value = np.asarray(self.embed_query(query), dtype=np.float32)
            if value.ndim == 1:
                value = value[None, :]
            if value.shape != (1, self.vectors.shape[1]) or not np.isfinite(value).all():
                raise ValueError('query embedding shape/finite contract violated')
            norm = float(np.linalg.norm(value.astype(np.float64)))
            if norm <= 1e-12:
                raise ValueError('query embedding is zero')
            self._query_cache[query] = value / norm
            self.embedding_calls += 1
        return self._query_cache[query]

    def _result(self, position: int, score: float, *, route: str, rank: int) -> dict:
        row = self.chunks[position]
        return {'rank': rank, 'chunk_id': row['chunk_id'], 'source_id': row['source_id'],
                'doc_id': row.get('doc_id'), 'text': row['text'], 'score': float(score), 'route': route,
                'page_start': row['page_start'], 'page_end': row['page_end'], 'section_path': row['section_path'],
                'document_sha256': row['document_sha256'], 'content_sha256': row['content_sha256'],
                'source_spans': row['source_spans'], 'parent_id': row['parent_id'],
                'parent_context': row.get('parent_context'),
                'context': row.get('context'), 'review_status': row['review_status'],
                'quality_flags': row['quality_flags'],
                'traceability_scope': 'artifact metadata integrity only; not external source correctness or semantic support'}

    def search(self, query: str, *, top_k: int = 5, filters: dict | None = None,
               rank_constant: int = 60, mmr_lambda: float = .75, max_per_document: int = 1,
               pool_size: int = 50) -> dict[str, dict]:
        if not isinstance(query, str) or not query.strip() or type(top_k) is not int or top_k < 1:
            raise ValueError('nonempty query and positive integer top_k are required')
        if type(mmr_lambda) not in {int, float} or not 0 <= mmr_lambda <= 1 or type(max_per_document) is not int or max_per_document < 1:
            raise ValueError('invalid diversification configuration')
        if type(pool_size) is not int or pool_size < top_k:
            raise ValueError('pool_size must be an integer at least top_k')
        reciprocal_rank_fusion([], rank_constant=rank_constant)
        selected = _selected(self.chunks, filters)
        names = ('bm25_only', 'dense_only', 'original_hybrid', 'rrf', 'rrf_mmr')
        if not selected:
            return {name: {'results': [], 'latency_ms': 0., 'eligible_chunks': 0, 'filters': filters or {}} for name in names}
        started = perf_counter()
        tokens = bm25_tokenize(query, version=self.artifact['manifest']['tokenizer_version'])
        bm25_scores = self.bm25.get_scores(tokens)
        sparse = sorted((i for i in selected if bm25_scores[i] > 0), key=lambda i: (-bm25_scores[i], self.chunks[i]['chunk_id']))
        sparse = sparse[:pool_size]
        bm25_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        vector = self._query(query)[0]
        dense_scores = self.vectors @ vector
        dense = sorted(selected, key=lambda i: (-float(dense_scores[i]), self.chunks[i]['chunk_id']))[:pool_size]
        dense_ms = (perf_counter() - started) * 1000
        def pack(order, scores, route, elapsed, implementation):
            return {'results': [self._result(i, scores[i], route=route, rank=rank) for rank, i in enumerate(order[:top_k], 1)],
                    'latency_ms': elapsed, 'eligible_chunks': len(selected), 'filters': filters or {}, 'implementation': implementation}
        modes = {'bm25_only': pack(sparse, bm25_scores, 'bm25', bm25_ms, 'raw_BM25_original_query'),
                 'dense_only': pack(dense, dense_scores, 'dense', dense_ms, 'cosine_original_query')}
        started = perf_counter()
        production = _SafeDiagnosticRuntime(self.artifact, self.cfg, selected, self._query)
        result = production.hybrid(query, top_k)
        positions = [r['chunk_id'] - 1 for r in result['results']]
        scores = {r['chunk_id'] - 1: r['final_score'] for r in result['results']}
        modes['original_hybrid'] = pack(positions, scores, 'production_hybrid', (perf_counter()-started)*1000,
                                        'production_query_plan_merge_rerank')
        started = perf_counter()
        fused = reciprocal_rank_fusion([[str(i) for i in dense], [str(i) for i in sparse]], rank_constant=rank_constant)
        rrf_scores = {int(i): score for i, score in fused.items()}
        order = sorted(rrf_scores, key=lambda i: (-rrf_scores[i], self.chunks[i]['chunk_id']))
        rrf_ms = (perf_counter()-started)*1000
        modes['rrf'] = pack(order, rrf_scores, 'rrf', dense_ms+bm25_ms+rrf_ms, 'unweighted_two_channel_RRF')
        started = perf_counter()
        picked: list[int] = []
        doc_count: dict[str, int] = {}
        remaining = set(order)
        max_score = max(rrf_scores.values(), default=1)
        while remaining and len(picked) < top_k:
            eligible = [i for i in remaining if doc_count.get(self.chunks[i]['source_id'], 0) < max_per_document]
            if not eligible:
                break
            def score(i):
                redundancy = max((float(self.vectors[i] @ self.vectors[j]) for j in picked), default=0.)
                return mmr_lambda * rrf_scores[i] / max_score - (1-mmr_lambda) * max(0., redundancy)
            chosen = sorted(eligible, key=lambda i: (-score(i), self.chunks[i]['chunk_id']))[0]
            picked.append(chosen)
            remaining.remove(chosen)
            doc = self.chunks[chosen]['source_id']; doc_count[doc] = doc_count.get(doc, 0)+1
        modes['rrf_mmr'] = pack(picked, rrf_scores, 'rrf_mmr', dense_ms+bm25_ms+rrf_ms+(perf_counter()-started)*1000,
                               'RRF_relevance_MMR_cosine_redundancy_with_document_cap')
        for mode in modes.values():
            mode['configuration'] = {'rank_constant': rank_constant, 'mmr_lambda': mmr_lambda, 'max_per_document': max_per_document,
                                      'pool_size': pool_size, 'top_k': top_k}
            mode['latency_scope'] = 'sequential_ablation; cached query vectors may be reused; not a cold-start SLA'
            mode['memory'] = memory_usage()
        return modes
