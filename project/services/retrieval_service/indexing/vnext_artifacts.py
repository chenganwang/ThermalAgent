"""Immutable experimental indexes from structured chunks; never production paths.

Persist only JSON/JSONL, numeric NPZ and native FAISS. Embeddings are supplied by
the caller, so importing/building does not implicitly load or download a model.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Callable, Sequence

import numpy as np

from ..bm25_tokenizer import CURRENT_TOKENIZER_VERSION, bm25_tokenize, require_tokenizer_version
from .artifact_io import read_faiss_index, write_faiss_index, sha256_file

SCHEMA_VERSION = 'thermal-vnext-candidate-v1'
CHUNK_SCHEMA_VERSION = 'structured-chunk-provenance-v1'
REVIEW_STATES = frozenset({'machine_draft', 'pending_review', 'reviewed', 'published', 'rejected'})
ARTIFACT_FILES = frozenset({'chunks.jsonl', 'vectors.npz', 'bm25.json', 'faiss.index'})


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(canonical_json(value) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def memory_usage() -> dict[str, Any]:
    try:
        import psutil
        info = psutil.Process().memory_info()
        return {'rss_bytes': info.rss, 'peak_working_set_bytes': getattr(info, 'peak_wset', None),
                'scope': 'whole_current_process; peak may include earlier sequential work'}
    except ImportError:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                                                        'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                                                        'PagefileUsage', 'PeakPagefileUsage')]
            kernel, psapi = ctypes.WinDLL('kernel32', use_last_error=True), ctypes.WinDLL('psapi', use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = Counters(); counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return {'rss_bytes': counters.WorkingSetSize, 'peak_working_set_bytes': counters.PeakWorkingSetSize,
                        'provider': 'Windows_GetProcessMemoryInfo',
                        'scope': 'whole_current_process; peak may include earlier sequential work'}
            return {'rss_bytes': None, 'peak_working_set_bytes': None, 'status': 'Windows_memory_query_failed',
                    'winerror': ctypes.get_last_error()}
        return {'rss_bytes': None, 'peak_working_set_bytes': None, 'status': 'psutil_unavailable_on_non_Windows'}


def validate_chunks(records: Sequence[dict]) -> list[dict]:
    if not records:
        raise ValueError('candidate requires at least one nonempty source chunk')
    seen = set()
    result = []
    for record in records:
        row = json.loads(canonical_json(record))
        for key in ('chunk_id', 'source_id', 'text', 'document_sha256'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f'chunk requires nonempty string {key}')
        if row['chunk_id'] in seen:
            raise ValueError('duplicate chunk_id')
        seen.add(row['chunk_id'])
        if not re.fullmatch('[0-9a-fA-F]{64}', row['document_sha256']):
            raise ValueError('document_sha256 must identify actual source bytes')
        for key in ('page_start', 'page_end'):
            if type(row.get(key)) is not int or row[key] < 1:
                raise ValueError('source pages must be positive integers')
        if row['page_end'] < row['page_start']:
            raise ValueError('source page range is reversed')
        row.setdefault('review_status', 'machine_draft')
        if row['review_status'] not in REVIEW_STATES:
            raise ValueError('unknown review_status')
        row.setdefault('section_path', row.get('section') or [])
        row.setdefault('parent_id', None)
        row.setdefault('quality_flags', [])
        if not isinstance(row['quality_flags'], list) or not all(isinstance(flag, str) for flag in row['quality_flags']):
            raise ValueError('quality_flags must be a string array')
        if row['parent_id'] is not None and (not isinstance(row['parent_id'], str) or not row['parent_id']):
            raise ValueError('parent_id must be a nonempty string or null')
        if row.get('parent_context'):
            parent = row['parent_context']
            if not isinstance(parent, dict) or parent.get('parent_id') is not None:
                raise ValueError('parent context must be a single original parent, not recursive')
            parent = validate_chunks([parent])[0]
            if parent['chunk_id'] != row['parent_id'] or parent['source_id'] != row['source_id'] or parent['document_sha256'] != row['document_sha256']:
                raise ValueError('parent context identity/source mismatch')
            row['parent_context'] = parent
        row.setdefault('source_spans', [])
        if not isinstance(row['source_spans'], list):
            raise ValueError('source_spans must be an array')
        for span in row['source_spans']:
            if not isinstance(span, dict) or not isinstance(span.get('block_id'), str) or not span['block_id']:
                raise ValueError('source span requires block_id')
            if type(span.get('start')) is not int or type(span.get('end')) is not int or not 0 <= span['start'] < span['end']:
                raise ValueError('source span offsets must be ordered nonnegative integers')
            if type(span.get('page')) is not int or not row['page_start'] <= span['page'] <= row['page_end']:
                raise ValueError('source span page is outside chunk range')
        row['content_sha256'] = hashlib.sha256(row['text'].encode('utf-8')).hexdigest()
        result.append(row)
    source_hashes: dict[str, set] = {}
    for row in result:
        source_hashes.setdefault(row['source_id'], set()).add(row['document_sha256'])
    if any(len(values) != 1 for values in source_hashes.values()):
        raise ValueError('one source_id cannot refer to multiple document byte versions in a candidate')
    return result


def read_chunks(path: str | Path) -> list[dict]:
    with Path(path).open(encoding='utf-8') as stream:
        return validate_chunks([json.loads(line) for line in stream if line.strip()])


def _vectors(value: Any, count: int, dimension: int | None = None) -> np.ndarray:
    raw = np.asarray(value)
    if raw.dtype.kind not in 'fiu' or raw.ndim != 2 or raw.shape[0] != count or raw.shape[1] < 1:
        raise ValueError('embedding must be a numeric matrix matching the chunk count')
    data = np.asarray(raw, dtype=np.float32)
    if dimension is not None and data.shape[1] != dimension:
        raise ValueError('embedding dimension changed between batches')
    norms = np.linalg.norm(data.astype(np.float64), axis=1)
    if not np.isfinite(data).all() or np.any(norms <= 1e-12):
        raise ValueError('embedding contains nonfinite or zero vector')
    return np.asarray(data / norms[:, None], dtype=np.float32)


def _write_npz(path: Path, **values: Any) -> None:
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('wb') as stream:
        np.savez_compressed(stream, **values)
    os.replace(temporary, path)


def build_candidate(
    records: Sequence[dict], output_dir: str | Path, *,
    embed_batch: Callable[[list[str]], np.ndarray], model_identity: dict,
    chunk_strategy: str, batch_size: int = 4, embedding_policy: dict | None = None,
    tokenizer_version: str = CURRENT_TOKENIZER_VERSION, resume: bool = False,
    source_collection_version: str | None = None,
) -> dict:
    """Build/resume one candidate. Completed versions can never be overwritten."""
    import faiss
    started = perf_counter()
    if type(batch_size) is not int or not 1 <= batch_size <= 4:
        raise ValueError('batch_size must be 1..4; multiple model processes are not supported')
    if not isinstance(model_identity, dict) or not model_identity.get('name') or not model_identity.get('revision'):
        raise ValueError('model identity requires name and pinned revision/fingerprint')
    tokenizer_version = require_tokenizer_version(tokenizer_version)
    rows = validate_chunks(records)
    tokens = [bm25_tokenize(row['text'], version=tokenizer_version) for row in rows]
    # Preserve original symbol/formula fragments. A chunk with no lexical
    # tokens contributes no sparse score; it is not replaced by invented words.
    if not any(tokens):
        raise ValueError('entire corpus has no BM25 lexical tokens')
    identity = {'schema_version': SCHEMA_VERSION, 'chunk_schema_version': CHUNK_SCHEMA_VERSION,
                'chunks_sha256': digest(rows), 'chunk_strategy': chunk_strategy,
                'model_identity': model_identity, 'embedding_policy': embedding_policy or {'document_strategy': 'provider_declared_single', 'normalize': True},
                'tokenizer_version': tokenizer_version, 'batch_size': batch_size,
                'source_collection_version': source_collection_version or digest(sorted({(r['source_id'], r['document_sha256']) for r in rows}))}
    build_id = digest(identity)
    target = Path(output_dir).resolve()
    if target.exists() and not resume:
        raise FileExistsError('candidate directory already exists; choose a new version or explicitly resume')
    target.mkdir(parents=True, exist_ok=True)
    if (target / 'manifest.json').exists():
        raise FileExistsError('completed candidate versions are immutable')
    lock = target / 'build.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        os.write(fd, canonical_json({'pid': os.getpid(), 'build_id': build_id}).encode())
        state_path = target / 'build_state.json'
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding='utf-8'))
            if state.get('build_id') != build_id:
                raise ValueError('resume inputs/model/policy differ from original build')
        else:
            state = {'build_id': build_id, 'identity': identity, 'completed_batches': []}
            atomic_json(state_path, state)
        batches = target / 'batches'
        batches.mkdir(exist_ok=True)
        chunks_path = target / 'chunks.jsonl'
        serialized_rows = ''.join(canonical_json(row) + '\n' for row in rows)
        if chunks_path.exists() and chunks_path.read_text(encoding='utf-8') != serialized_rows:
            raise ValueError('resume source chunks differ')
        chunks_path.write_text(serialized_rows, encoding='utf-8')
        all_vectors = []
        dimension = None
        for start in range(0, len(rows), batch_size):
            selected = rows[start:start + batch_size]
            batch_path = batches / f'{start:09d}.npz'
            existing = next((b for b in state['completed_batches'] if b['start'] == start), None)
            if existing:
                if sha256_file(batch_path) != existing['sha256']:
                    raise ValueError('resume batch hash mismatch')
                with np.load(batch_path, allow_pickle=False) as data:
                    if data['chunk_ids'].tolist() != [r['chunk_id'] for r in selected]:
                        raise ValueError('resume batch ID mismatch')
                    vectors = _vectors(data['vectors'], len(selected), dimension)
            else:
                vectors = _vectors(embed_batch([r['text'] for r in selected]), len(selected), dimension)
                _write_npz(batch_path, vectors=vectors, chunk_ids=np.array([r['chunk_id'] for r in selected], dtype=str))
                state['completed_batches'].append({'start': start, 'count': len(selected), 'sha256': sha256_file(batch_path)})
                atomic_json(state_path, state)
            dimension = vectors.shape[1]
            all_vectors.append(vectors)
        vectors = np.concatenate(all_vectors)
        index = faiss.IndexFlatIP(dimension)
        index.add(vectors)
        write_faiss_index(index, target / 'faiss.index')
        _write_npz(target / 'vectors.npz', vectors=vectors, chunk_ids=np.array([r['chunk_id'] for r in rows], dtype=str))
        atomic_json(target / 'bm25.json', {'tokenizer_version': tokenizer_version, 'k1': 1.5, 'b': .75, 'tokens': tokens})
        manifest = {**identity, 'build_id': build_id, 'status': 'complete', 'created_at': datetime.now(timezone.utc).isoformat(),
                    'chunk_count': len(rows), 'document_count': len({r['source_id'] for r in rows}), 'dimension': dimension,
                    'source_documents': sorted({(r['source_id'], r['document_sha256']) for r in rows}),
                    'dedupe_policy': 'preserve_all_source_chunks_report_exact_text_duplicates_v1',
                    'exact_duplicate_text_count': len(rows) - len({r['content_sha256'] for r in rows}),
                    'bm25_empty_document_count': sum(not values for values in tokens),
                    'review_counts': {status: sum(r['review_status'] == status for r in rows) for status in sorted(REVIEW_STATES)},
                    'normalize': True, 'faiss_metric': 'inner_product', 'faiss_class': 'IndexFlatIP',
                    'files': {name: sha256_file(target / name) for name in sorted(ARTIFACT_FILES)},
                    'build_seconds': perf_counter() - started, 'memory': memory_usage(),
                    'production_activation_allowed': False,
                    'release_blockers': ['experiment_only', 'independent_relevance_gold_and_release_regression_required'],
                    'evaluation': None}
        atomic_json(target / 'manifest.json', manifest)
        return manifest
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def load_candidate(path: str | Path) -> dict:
    """Validate complete artifacts before native FAISS parsing; no pickle reader."""
    target = Path(path).resolve()
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != SCHEMA_VERSION or manifest.get('chunk_schema_version') != CHUNK_SCHEMA_VERSION:
        raise ValueError('unsupported candidate schema version')
    version = require_tokenizer_version(manifest.get('tokenizer_version'))
    if manifest.get('status') != 'complete' or manifest.get('production_activation_allowed') is not False:
        raise ValueError('not a completed experiment-only candidate')
    if set(manifest.get('files', {})) != ARTIFACT_FILES:
        raise ValueError('unexpected artifact filenames')
    for name, expected in manifest['files'].items():
        if sha256_file(target / name) != expected:
            raise ValueError(f'artifact hash mismatch: {name}')
    rows = read_chunks(target / 'chunks.jsonl')
    if digest(rows) != manifest.get('chunks_sha256') or len(rows) != manifest['chunk_count']:
        raise ValueError('chunk content/count identity mismatch')
    source_documents = sorted({(row['source_id'], row['document_sha256']) for row in rows})
    if manifest.get('source_documents') != [list(value) for value in source_documents] or manifest.get('document_count') != len(source_documents):
        raise ValueError('source document manifest mismatch')
    bm25 = json.loads((target / 'bm25.json').read_text(encoding='utf-8'))
    if bm25.get('tokenizer_version') != version or bm25.get('tokens') != [bm25_tokenize(r['text'], version=version) for r in rows]:
        raise ValueError('BM25 lexical contract mismatch')
    with np.load(target / 'vectors.npz', allow_pickle=False) as data:
        if set(data.files) != {'vectors', 'chunk_ids'} or data['chunk_ids'].tolist() != [r['chunk_id'] for r in rows]:
            raise ValueError('vector ID mapping mismatch')
        vectors = _vectors(data['vectors'], len(rows), manifest['dimension'])
    index = read_faiss_index(target / 'faiss.index')
    if index.ntotal != len(rows) or index.d != manifest['dimension'] or index.metric_type != 0:
        raise ValueError('FAISS shape/metric mismatch')
    if not np.allclose(index.reconstruct_n(0, index.ntotal), vectors, rtol=1e-6, atol=1e-7):
        raise ValueError('FAISS vectors disagree with checked numeric archive')
    return {'path': target, 'manifest': manifest, 'chunks': rows, 'vectors': vectors, 'index': index, 'bm25': bm25}
