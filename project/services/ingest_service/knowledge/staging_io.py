"""Artifact validation for the public-source candidate pipeline (no network)."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from .staging_contracts import canonical_json, content_hash, normalized_claim, SCHEMA_VERSION
from .staging_store import make_record


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json_exclusive(path: str | Path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def verify_source_files(sources: list[dict], project_root: str | Path) -> dict:
    root = Path(project_root).resolve()
    accepted, rejected = [], []
    seen: set[str] = set()
    for source in sources:
        sid = source.get('source_id')
        errors = []
        if not isinstance(sid, str) or not sid or sid in seen:
            errors.append('missing_or_duplicate_source_id')
        seen.add(sid)
        license_data = source.get('license') or {}
        if license_data.get('allow_fulltext') is not True or not license_data.get('basis') or not license_data.get('url'):
            errors.append('missing_recorded_fulltext_legal_basis')
        if not str(source.get('url', '')).startswith('https://'):
            errors.append('https_source_url_required')
        relative = source.get('local_path') or source.get('file_path')
        if not relative:
            errors.append('metadata_only_source')
        else:
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                errors.append('source_path_outside_project')
            elif not path.is_file():
                errors.append('source_file_missing')
            elif hashlib.sha256(path.read_bytes()).hexdigest() != source.get('sha256'):
                errors.append('source_bytes_hash_mismatch')
        item = {'source_id': sid, 'errors': errors}
        if errors:
            rejected.append(item)
        else:
            accepted.append(source)
    return {'accepted': accepted, 'rejected': rejected, 'scope': 'Recorded legal basis plus local byte identity; not a legal or domain-review attestation.'}


def records_from_artifacts(sources: list[dict], chunks: list[dict], units: list[dict], questions: list[dict] | None = None) -> list[dict]:
    records = []
    for kind, values in (('source', sources), ('chunk', chunks), ('unit', units), ('qa', questions or [])):
        for item in values:
            payload = dict(item)
            # Each immutable import records its original machine state; human
            # review events are stored separately by StagingStore.record_review.
            payload['review_status'] = 'pending_review'
            payload['human_reviewed'] = False
            records.append(make_record(kind, payload))
    unique = {r['record_id']: r for r in records}
    return sorted(unique.values(), key=lambda r: r['record_id'])


def write_import_package(output_dir: str | Path, *, sources: list[dict], documents: list[dict], chunks: list[dict], candidate_result: dict, questions: list[dict] | None = None):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    records = records_from_artifacts(sources, chunks, candidate_result['candidates'], questions)
    artifacts = {
        'sources.json': sources, 'documents.json': documents, 'chunks.json': chunks,
        'knowledge_candidates.json': candidate_result, 'qa_candidates.json': questions or [], 'records.json': records,
    }
    files = {}
    for name, value in artifacts.items():
        write_json_exclusive(out / name, value)
        files[name] = hashlib.sha256((out / name).read_bytes()).hexdigest()
    manifest = {'schema_version': SCHEMA_VERSION, 'files': files,
                'counts': {'sources': len(sources), 'documents': len(documents), 'chunks': len(chunks),
                           'candidate_units': len(candidate_result['candidates']), 'qa_candidates': len(questions or []),
                           'records': len(records), 'human_reviewed_increment': 0, 'published_increment': 0},
                'candidate_dataset_sha256': content_hash([r['record_id'] for r in records]),
                'production_index_activation_allowed': False,
                'reason': 'Candidate preparation is not independent domain or retrieval-quality acceptance.'}
    write_json_exclusive(out / 'manifest.json', manifest)
    return manifest


def validate_import_package(path: str | Path, *, project_root: str | Path) -> dict:
    from .staging_contracts import validate_candidate
    base = Path(path).resolve()
    manifest = read_json(base / 'manifest.json')
    if manifest.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('unsupported_import_schema')
    required_files = {'sources.json', 'documents.json', 'chunks.json',
                      'knowledge_candidates.json', 'qa_candidates.json', 'records.json'}
    if set(manifest.get('files', {})) != required_files:
        raise ValueError('package_required_artifacts_not_bound')
    for name, expected in manifest.get('files', {}).items():
        artifact = (base / name).resolve()
        if not artifact.is_relative_to(base) or not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
            raise ValueError('package_artifact_identity_failed')
    sources = read_json(base / 'sources.json')
    checked = verify_source_files(sources, project_root)
    if checked['rejected']:
        raise ValueError('source_precheck_failed:' + canonical_json(checked['rejected']))
    documents = read_json(base / 'documents.json')
    by_source = {s['source_id']: s for s in sources}
    blocks = {}
    for doc in documents:
        meta = doc['document']
        if meta.get('source_id') not in by_source or meta.get('sha256') != by_source[meta['source_id']]['sha256']:
            raise ValueError('document_source_version_mismatch')
        for block in doc['blocks']:
            item = {**block, 'source_id': meta['source_id']}
            if item['block_id'] in blocks and blocks[item['block_id']] != item:
                raise ValueError('duplicate_block_identity')
            blocks[item['block_id']] = item
    candidate_artifact = read_json(base / 'knowledge_candidates.json')
    units = candidate_artifact['candidates']
    for candidate in units:
        errors = validate_candidate(candidate, by_source, blocks)
        if errors:
            raise ValueError('candidate_evidence_invalid:' + ','.join(errors))
    chunks = read_json(base / 'chunks.json')
    for chunk in chunks:
        if chunk.get('source_id') not in by_source or chunk.get('document_sha256') != by_source[chunk['source_id']]['sha256']:
            raise ValueError('chunk_source_identity_invalid')
        if not chunk.get('text') or not chunk.get('source_spans'):
            raise ValueError('chunk_content_or_provenance_missing')
        original_parts = []
        for span in chunk['source_spans']:
            block = blocks.get(span.get('block_id'))
            if not block or block['source_id'] != chunk['source_id'] or block['page'] != span.get('page'):
                raise ValueError('chunk_evidence_location_invalid')
            start, end = span.get('start'), span.get('end')
            if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) or isinstance(end, bool) or not 0 <= start < end <= len(block['text']):
                raise ValueError('chunk_evidence_span_invalid')
            original_parts.append(block['text'][start:end])
        if normalized_claim(' '.join(original_parts)) != normalized_claim(chunk['text']):
            raise ValueError('chunk_text_not_exact_source_spans')
    from .question_candidates import validate_questions
    questions = read_json(base / 'qa_candidates.json')
    errors = validate_questions(questions, by_source, blocks)
    if errors:
        raise ValueError('qa_evidence_invalid:' + ','.join(errors))
    from .numeric_quality import assess_record_numeric_quality
    question_by_id = {q['case_id']:q for q in questions}
    for check in candidate_artifact.get('numeric_quality',{}).get('qa_checks',[]):
        question = question_by_id.get(check.get('case_id'))
        if not question or question['version_id'] != check.get('question_version_id'):
            raise ValueError('numeric_check_question_binding_invalid')
        actual_check = assess_record_numeric_quality({'arithmetic_spec':check.get('spec')})
        if actual_check != check.get('result') or actual_check['status']=='failed':
            raise ValueError('numeric_check_reproduction_failed')
    expected = records_from_artifacts(sources, chunks, units, questions)
    actual = read_json(base / 'records.json')
    if expected != actual:
        raise ValueError('records_do_not_match_validated_artifacts')
    if content_hash([r['record_id'] for r in actual]) != manifest.get('candidate_dataset_sha256'):
        raise ValueError('dataset_identity_failed')
    return {'manifest': manifest, 'records': actual, 'checks': {'source_hashes': True, 'source_license_basis_recorded': True,
            'candidate_exact_spans': True, 'chunk_source_spans': True, 'human_review': 'unavailable',
            'production_index_activation': False, 'production_append_scope': 'pending-review data layer only'}}
