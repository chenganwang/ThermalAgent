from __future__ import annotations

import json
import pickle
import time
from dataclasses import dataclass

from services.ingest_service.chunking.pack import strip_packed_meta
from .config import AppConfig
from .bm25_tokenizer import (
    bm25_tokenize, CURRENT_TOKENIZER_VERSION, LEGACY_TOKENIZER_VERSION,
)
from .bm25_artifact import load_bm25_payload  # Public re-export for existing callers.


def is_bm25_eligible_text(text: str, *, version: str = CURRENT_TOKENIZER_VERSION) -> bool:
    return bool(bm25_tokenize(text, version=version))


@dataclass
class BM25IndexManager:
    cfg: AppConfig

    def ensure_dir(self) -> None:
        self.cfg.paths.bm25_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.paths.bm25_corpus_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.paths.bm25_meta_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, *, chunk_ids: list[int], tokenized_corpus: list[list[str]], corpus_texts: list[str]) -> None:
        if not len(chunk_ids) == len(tokenized_corpus) == len(corpus_texts) or tokenized_corpus != [bm25_tokenize(text) for text in corpus_texts]:
            raise ValueError('BM25 tokenized corpus does not match the current tokenizer')
        self.ensure_dir()
        payload = {
            'tokenizer_version': CURRENT_TOKENIZER_VERSION,
            'chunk_ids': chunk_ids,
            'tokenized_corpus': tokenized_corpus,
            'corpus_texts': corpus_texts,
        }
        with open(self.cfg.paths.bm25_corpus_path, 'wb') as f:
            pickle.dump(payload, f)
        meta = {
            'tokenizer_version': CURRENT_TOKENIZER_VERSION,
            'updated_at': int(time.time()),
            'model_name': 'bm25',
            'chunk_count': len(chunk_ids),
            'enabled': bool(self.cfg.bm25.enabled),
            'k1': self.cfg.bm25.k1,
            'b': self.cfg.bm25.b,
        }
        self.cfg.paths.bm25_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    def load(self):
        from rank_bm25 import BM25Okapi  # type: ignore
        if not self.cfg.paths.bm25_corpus_path.exists():
            return None, [], []
        payload, version = load_bm25_payload(self.cfg.paths.bm25_corpus_path, self.cfg.paths.bm25_meta_path)
        chunk_ids = payload.get('chunk_ids', [])
        tokenized_corpus = payload.get('tokenized_corpus', [])
        corpus_texts = payload.get('corpus_texts', [])
        bm25 = BM25Okapi(tokenized_corpus, k1=self.cfg.bm25.k1, b=self.cfg.bm25.b)
        # Bind the query tokenizer to this exact loaded model, not a later read
        # of metadata that could select another generation.
        bm25.tokenizer_version = version
        return bm25, chunk_ids, corpus_texts

    def read_meta(self) -> dict:
        if not self.cfg.paths.bm25_meta_path.exists():
            return {}
        try:
            return json.loads(self.cfg.paths.bm25_meta_path.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def search(self, query: str, *, topn: int | None = None) -> list[tuple[int, float]]:
        bm25, chunk_ids, _texts = self.load()
        if bm25 is None:
            return []
        topn = topn or self.cfg.bm25.topn
        q_tokens = bm25_tokenize(query, version=bm25.tokenizer_version)
        if not q_tokens:
            return []
        scores = bm25.get_scores(q_tokens)
        ranked = sorted(enumerate(scores.tolist() if hasattr(scores, 'tolist') else list(scores)), key=lambda x: x[1], reverse=True)
        out = []
        for idx, score in ranked[:topn]:
            if score <= 0:
                continue
            out.append((int(chunk_ids[idx]), float(score)))
        return out


def rebuild_bm25_index(cfg: AppConfig, db) -> None:
    mgr = BM25IndexManager(cfg)
    if not cfg.bm25.enabled:
        mgr.ensure_dir()
        meta = mgr.read_meta()
        if cfg.paths.bm25_corpus_path.exists():
            _, version = load_bm25_payload(cfg.paths.bm25_corpus_path, cfg.paths.bm25_meta_path)
            meta['tokenizer_version'] = version
        meta.update(enabled=False, updated_at=int(time.time()))
        mgr.cfg.paths.bm25_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        return
    rows = db.list_active_chunks_for_bm25()
    chunk_ids: list[int] = []
    corpus_texts: list[str] = []
    tokenized_corpus: list[list[str]] = []
    for chunk_id, text, _chunk_type in rows:
        cleaned = strip_packed_meta(str(text or ''))
        toks = bm25_tokenize(cleaned)
        if not toks:
            continue
        chunk_ids.append(int(chunk_id))
        corpus_texts.append(cleaned)
        tokenized_corpus.append(toks)
    mgr.save(chunk_ids=chunk_ids, tokenized_corpus=tokenized_corpus, corpus_texts=corpus_texts)


def validate_bm25_vs_db(cfg: AppConfig, db, *, bundle=None) -> dict:
    from .indexing.active_bundle import resolve_active_bundle

    bundle = bundle or resolve_active_bundle(cfg)
    cfg = bundle.cfg
    mgr = BM25IndexManager(cfg)
    meta = mgr.read_meta()
    _index, indexed_ids, _texts = mgr.load()
    tokenizer_version = _index.tokenizer_version if _index is not None else LEGACY_TOKENIZER_VERSION
    chunk_count = len(indexed_ids)
    raw_rows = db.list_active_chunks_for_bm25() if cfg.bm25.enabled else []
    eligible = [(chunk_id, text, chunk_type) for chunk_id, text, chunk_type in raw_rows if is_bm25_eligible_text(text, version=tokenizer_version)]
    db_count = len(eligible) if cfg.bm25.enabled else 0
    mapping_matches = bundle.mapping_chunk_ids is None or list(bundle.mapping_chunk_ids) == list(indexed_ids)
    database_ids_match = set(indexed_ids) == {int(row[0]) for row in eligible}
    return {
        'bm25_chunk_count': chunk_count,
        'bm25_enabled': bool(meta.get('enabled', cfg.bm25.enabled)),
        'db_active_chunks_for_bm25': len(raw_rows),
        'db_bm25_eligible_chunks': db_count,
        'db_bm25_skipped_chunks': max(0, len(raw_rows) - db_count),
        'index_generation': bundle.version,
        'tokenizer_version': tokenizer_version,
        'mapping_order_matches_faiss': mapping_matches,
        'database_chunk_ids_match': database_ids_match,
        'is_consistent': (not cfg.bm25.enabled) or (chunk_count == db_count and database_ids_match and mapping_matches),
        'meta': meta,
    }
