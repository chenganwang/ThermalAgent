"""SELECT-only snapshot for a controlled legacy-corpus expansion experiment.

Reads production FAISS shape and DB mapping, never BM25 pickle. Database chunk
spans are explicitly labeled as DB-text coordinates, not recovered PDF blocks.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from .artifact_io import read_faiss_index, sha256_file
from .vnext_artifacts import atomic_json, canonical_json, digest, validate_chunks


def legacy_rows(mapping: list[tuple], catalog: dict, documents: dict) -> list[dict]:
    positions = [int(row[1]) for row in mapping]
    ids = [int(row[0]) for row in mapping]
    if positions != list(range(len(positions))) or len(ids) != len(set(ids)):
        raise ValueError('legacy mapping must have unique chunk IDs and contiguous vector positions')
    rows = []
    for chunk_id in ids:
        if chunk_id not in catalog:
            raise ValueError('production mapping points to an unavailable active chunk')
        row = catalog[chunk_id]
        doc_id = int(row['document_id'])
        document = documents[doc_id]
        text = row['text']
        rows.append({'chunk_id': f'legacy_chunk_{chunk_id}', 'legacy_chunk_id': chunk_id,
                     'source_id': f'legacy_doc_{doc_id}', 'doc_id': doc_id, 'document_sha256': document['sha256'],
                     'text': text, 'page_start': row['page_start'], 'page_end': row['page_end'],
                     'section_path': row.get('section_title') or [], 'parent_id': None,
                     'chunk_type': row.get('chunk_type') or 'text', 'title': document.get('title'),
                     'review_status': 'machine_draft', 'human_reviewed': False,
                     'source_spans': [{'block_id': f'legacy_db_chunk_{chunk_id}', 'start': 0, 'end': len(text), 'page': row['page_start']}],
                     'span_coordinate_system': 'legacy_database_chunk_text_not_pdf_block',
                     'quality_flags': ['legacy_extracted_text_not_reparsed', 'original_pdf_block_offsets_unavailable'],
                     'source_file_verification': document.get('file_verification')})
    return validate_chunks(rows)


def convert_legacy_cases(value: dict) -> list[dict]:
    cases = []
    for case in value['cases']:
        cases.append({'case_id': case['case_id'], 'query': case['query'], 'category': case.get('category'),
                      'corpus_scope': case.get('corpus_scope'), 'split': 'development',
                      'label_status': 'machine_reference', 'human_reviewed': False, 'used_for_tuning': False,
                      'historical_seen_diagnostic': True,
                      'relevant_chunk_ids': [f'legacy_chunk_{i}' for i in case.get('relevant_chunk_ids', [])],
                      'acceptable_chunk_ids': [f'legacy_chunk_{i}' for i in case.get('acceptable_chunk_ids', [])],
                      'relevant_source_ids': [f'legacy_doc_{i}' for i in case.get('expected_document_ids', [])],
                      'forbidden_source_ids': [f'legacy_doc_{i}' for i in case.get('forbidden_document_ids', [])],
                      'answerable': True,
                      'label_note': 'Original machine reference IDs preserved; confusion controls are not unanswerable cases.'})
    return cases


def export_legacy_snapshot(cfg, output_dir: str | Path, diagnostic_path: str | Path) -> dict:
    from .diagnostics.read_only_store import SelectOnlyChunkStore
    folder = Path(output_dir).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    paths = {'faiss': cfg.paths.faiss_index_path, 'faiss_meta': cfg.paths.faiss_meta_path,
             'bm25': cfg.paths.bm25_corpus_path, 'bm25_meta': cfg.paths.bm25_meta_path}
    before = {name: sha256_file(path) for name, path in paths.items()}
    count = int(read_faiss_index(paths['faiss']).ntotal)
    store = SelectOnlyChunkStore(cfg)
    try:
        mapping = store.fetchall('SELECT chunk_id, vector_pos FROM embeddings ORDER BY vector_pos')
        if len(mapping) != count:
            raise ValueError('production FAISS count and SELECT-only mapping count disagree')
        catalog = store.load_chunk_catalog()
        doc_rows = store.fetchall('SELECT id, sha256, title, local_path FROM documents ORDER BY id')
        documents = {}
        for doc_id, sha, title, local_path in doc_rows:
            documents[int(doc_id)] = {'sha256': str(sha), 'title': title}
            path = Path(str(local_path or ''))
            verified = {'status': 'source_file_unavailable', 'database_sha256': str(sha)}
            if local_path and path.is_file():
                actual = sha256_file(path)
                verified = {'status': 'verified' if actual == sha else 'hash_mismatch', 'actual_sha256': actual, 'database_sha256': str(sha)}
                if actual != sha:
                    raise ValueError(f'legacy source {doc_id} bytes differ from registered SHA256')
            documents[int(doc_id)]['file_verification'] = verified
        rows = legacy_rows(mapping, catalog, documents)
        (folder/'chunks.jsonl').write_text(''.join(canonical_json(row)+'\n' for row in rows), encoding='utf-8')
        cases = convert_legacy_cases(json.loads(Path(diagnostic_path).read_text(encoding='utf-8')))
        atomic_json(folder/'cases.json', cases)
        after = {name: sha256_file(path) for name, path in paths.items()}
        if before != after:
            raise ValueError('production index changed during read-only snapshot')
        manifest = {'schema_version': 'thermal-vnext-legacy-snapshot-v1', 'chunk_count': len(rows),
                    'document_count': len({r['source_id'] for r in rows}), 'source_documents': documents,
                    'chunks_sha256': digest(rows), 'chunks_file_sha256': sha256_file(folder/'chunks.jsonl'),
                    'cases_file_sha256': sha256_file(folder/'cases.json'), 'original_diagnostic_sha256': sha256_file(diagnostic_path),
                    'production_hashes_before': before, 'production_hashes_after': after,
                    'database_statement_types': dict(Counter(store.executed_statements)), 'rejected_write_attempts': store.rejected_write_attempts,
                    'production_activated': False, 'legacy_pickle_loaded': False,
                    'scope': 'same current model/lexical policy legacy rebuild versus its expansion; not historical production rank equivalence'}
        atomic_json(folder/'snapshot.json', manifest)
        return manifest
    finally:
        store.close()
