"""Explicit single-process, offline model session for candidate experiments.

No model is loaded at import time. The caller must supply an existing local
model directory. Numeric caches are bound to model-file hashes and policy.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
from time import perf_counter

import numpy as np

from .artifact_io import sha256_file
from .vnext_artifacts import _vectors, _write_npz, atomic_json, digest, memory_usage
from .windowed_embeddings import WindowedDocumentEmbedder


class LocalModelSession:
    def __init__(self, model_dir: str | Path, cache_dir: str | Path, *, threads: int = 2):
        directory = Path(model_dir).resolve()
        if not directory.is_dir() or not (directory / 'config.json').is_file():
            raise ValueError('model_dir must be an existing local model directory; downloads are disabled')
        if type(threads) is not int or not 1 <= threads <= 4:
            raise ValueError('model CPU thread budget must be 1..4')
        weights = [p for p in directory.rglob('*') if p.is_file() and p.suffix in {'.safetensors', '.bin'}]
        if not weights:
            raise ValueError('local model weights are missing')
        files = {str(p.relative_to(directory)).replace('\\', '/'): sha256_file(p)
                 for p in sorted(directory.rglob('*')) if p.is_file() and p.suffix in {'.json', '.txt', '.safetensors', '.bin', '.model'}}
        self.identity = {'name': directory.name, 'revision': digest(files), 'local_path': str(directory),
                         'files_sha256': files,
                         'packages': {p: importlib.metadata.version(p) for p in ('sentence-transformers', 'transformers', 'torch')}}
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(threads)
        started = perf_counter()
        self.model = SentenceTransformer(str(directory), local_files_only=True, device='cpu', trust_remote_code=False)
        self.document_provider = WindowedDocumentEmbedder(self.model, overlap=24, batch_size=4, normalize=True)
        self.policy = self.document_provider.policy
        self.policy.update({'input_scope': 'chunk_body_only; parent/context retained as provenance, not synthesized into embeddings',
                            'semantic_block_strategy': 'same token windows as documents; no content truncation',
                            'execution_batch_size': 4, 'device': 'cpu', 'cpu_threads': threads})
        self.load_seconds = perf_counter() - started
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_identity = {'model': self.identity, 'policy': self.policy}
        self.cache_version = digest(cache_identity)
        identity_path = self.cache_dir / 'identity.json'
        if identity_path.exists():
            if json.loads(identity_path.read_text(encoding='utf-8')) != cache_identity:
                raise ValueError('embedding cache model/policy identity differs')
        else:
            atomic_json(identity_path, cache_identity)
        self.stats = {'document_requests': 0, 'query_requests': 0, 'cache_hits': 0, 'encoded_texts': 0,
                      'encode_seconds': 0., 'query_truncated_texts': 0}

    def _encode(self, texts: list[str], kind: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.model.get_sentence_embedding_dimension()), dtype=np.float32)
        self.stats[f'{kind}_requests'] += len(texts)
        rows: list[np.ndarray | None] = [None] * len(texts)
        missing: dict[str, tuple[str, list[int]]] = {}
        for i, text in enumerate(texts):
            key = digest({'cache_version': self.cache_version, 'kind': kind, 'text': text})
            path = self.cache_dir / (key + '.npz')
            if path.exists():
                with np.load(path, allow_pickle=False) as archive:
                    if archive['key'].item() != key:
                        raise ValueError('embedding cache identity mismatch')
                    rows[i] = _vectors(archive['vectors'], 1, self.model.get_sentence_embedding_dimension())[0]
                self.stats['cache_hits'] += 1
            elif key in missing:
                missing[key][1].append(i)
            else:
                missing[key] = (text, [i])
        entries = list(missing.items())
        for start in range(0, len(entries), 4):
            batch = entries[start:start+4]
            strings = [value[0] for _, value in batch]
            began = perf_counter()
            if kind == 'document':
                vectors = self.document_provider(strings)
            else:
                for text in strings:
                    count = len(self.model.tokenizer(text, add_special_tokens=True, truncation=False)['input_ids'])
                    self.stats['query_truncated_texts'] += int(count > self.model.max_seq_length)
                vectors = self.model.encode(strings, normalize_embeddings=True, batch_size=4, show_progress_bar=False)
            vectors = _vectors(vectors, len(strings), self.model.get_sentence_embedding_dimension())
            self.stats['encode_seconds'] += perf_counter() - began
            self.stats['encoded_texts'] += len(strings)
            for (key, (_, positions)), vector in zip(batch, vectors):
                _write_npz(self.cache_dir / (key+'.npz'), key=np.array(key), vectors=vector[None, :])
                for position in positions:
                    rows[position] = vector
        return np.asarray(rows, dtype=np.float32)

    def documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(list(texts), 'document')

    def query(self, query: str) -> np.ndarray:
        return self._encode([query], 'query')

    def report(self) -> dict:
        return {'model_identity': self.identity, 'embedding_policy': self.policy, 'model_load_seconds': self.load_seconds,
                'statistics': dict(self.stats), 'token_windows': dict(self.document_provider.statistics),
                'memory': memory_usage(), 'model_process_count': 1, 'paid_api_calls': 0}
