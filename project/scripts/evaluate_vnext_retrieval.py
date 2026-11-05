"""Build and compare local VNext candidates without changing active indexes.

Examples (one explicit local model process, never network downloads):
  python scripts/evaluate_vnext_retrieval.py experiment --parser-results PATH \
    --cases PATH --output-dir NEW_PATH --model-dir LOCAL_MODEL_DIRECTORY
  python scripts/evaluate_vnext_retrieval.py evaluate --candidate fixed=PATH \
    --cases PATH --output-dir NEW_PATH --query-vectors SAFE_JSON_FILE

The experiment's test split is reported with label provenance; machine-authored
test questions cannot satisfy the independent-gold release gate.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.retrieval_service.config import load_config
from services.retrieval_service.indexing.artifact_io import sha256_file
from services.retrieval_service.indexing.vnext_artifacts import atomic_json, build_candidate, canonical_json, digest, load_candidate, read_chunks
from services.retrieval_service.indexing.vnext_evaluation import evaluate_candidates, validate_cases
from services.retrieval_service.indexing.vnext_retrieval import CandidateRuntime


def _json_cases(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    cases = value if isinstance(value, list) else value.get('cases', value.get('questions', []))
    validate_cases(cases)
    return cases


def load_chunk_inputs(path: Path, strategy: str) -> list[dict]:
    rows = read_chunks(path)
    if strategy != 'parent_child':
        return rows
    parents_path = path.with_name('parents.jsonl')
    parents = {row['chunk_id']: row for row in read_chunks(parents_path)}
    for row in rows:
        if not row.get('parent_id') or row['parent_id'] not in parents:
            raise ValueError('parent-child experiment requires the original parent artifact')
        row['parent_context'] = parents[row['parent_id']]
    # Child body is indexed; its original parent is returned with separate
    # provenance. This does not invent extra contiguous child text or count a
    # parent as another independently relevant retrieved chunk.
    from services.retrieval_service.indexing.vnext_artifacts import validate_chunks
    return validate_chunks(rows)


def _resolve_parser_path(value: str, results_path: Path) -> Path:
    given = Path(value)
    for path in (given, ROOT / given, results_path.parent / given):
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f'parser record missing: {value}')


def verify_semantic_source(document: dict, result: dict) -> None:
    """Check exact original text, offsets, pages, geometry and derived metadata."""
    from services.ingest_service.structured_chunking import _make
    blocks = {row['block_id']: row for row in document['blocks'] if row['text'].strip() and not row.get('exclude_from_retrieval')}
    if result.get('strategy') != 'semantic' or result.get('status') != 'ok' or not result.get('chunks'):
        raise ValueError('semantic cache does not contain a complete dense semantic result')
    if result.get('semantic_mode') != 'supplied_dense_vectors' or not result.get('options', {}).get('embedding_digest'):
        raise ValueError('semantic cache lacks actual dense-vector provenance')
    for row in result['chunks']:
        if not row.get('source_spans'):
            raise ValueError('semantic source spans missing')
        for span in row['source_spans'] + row.get('context', {}).get('source_spans', []):
            block = blocks.get(span.get('block_id'))
            if (not block or type(span.get('start')) is not int or type(span.get('end')) is not int
                    or not 0 <= span['start'] < span['end'] <= len(block['text'])
                    or span.get('page') != block['page'] or span.get('bbox') != block.get('bbox')):
                raise ValueError('semantic source span differs from parsed original')
        expected = _make(document, row['source_spans'], 'semantic', result['options'], parent_id=row.get('parent_id'),
                         context_spans=row.get('context', {}).get('source_spans', []))
        if expected != row:
            raise ValueError('semantic cached text/metadata does not reconstruct from original spans')


def _semantic_chunks(parser_results: Path, output: Path, session, *, resume: bool) -> Path:
    from services.ingest_service.structured_chunking import chunk_document
    report = json.loads(parser_results.read_text(encoding='utf-8'))
    options = dict(report['policy'].get('options') or {})
    options['embedding_policy'] = session.policy
    folder = output / 'semantic_chunks'
    folder.mkdir(exist_ok=True)
    chunks, records = [], []
    for record in report['records']:
        if record.get('status') != 'parsed':
            continue
        path = _resolve_parser_path(record['parsed_path'], parser_results)
        document = json.loads(path.read_text(encoding='utf-8'))
        identity = digest({'document_sha256': sha256_file(path), 'options': options, 'model': session.identity})
        result_path = folder / (identity+'.json')
        checksum_path = folder / (identity+'.cache.json')
        if result_path.exists() and resume:
            if not checksum_path.is_file():
                raise ValueError('semantic cache checksum missing; rebuild or verify in a new version')
            checksum = json.loads(checksum_path.read_text(encoding='utf-8'))
            if checksum.get('identity') != identity or checksum.get('result_sha256') != sha256_file(result_path):
                raise ValueError('semantic cache hash/identity mismatch')
            result = json.loads(result_path.read_text(encoding='utf-8'))
        elif result_path.exists():
            raise FileExistsError('semantic document result already exists; use resume')
        else:
            result = chunk_document(document, 'semantic', options, embedding_provider=session.documents)
            verify_semantic_source(document, result)
            atomic_json(result_path, result)
            atomic_json(checksum_path, {'schema_version': 'thermal-semantic-cache-v1', 'identity': identity,
                                       'result_sha256': sha256_file(result_path), 'parsed_document_sha256': sha256_file(path)})
        verify_semantic_source(document, result)
        if result.get('status') != 'ok' or not result.get('chunks'):
            raise ValueError(f"semantic chunking unavailable for {record['source_id']}: {result.get('status')}")
        chunks.extend(result['chunks'])
        records.append({'source_id': record['source_id'], 'result_path': str(result_path), 'sha256': sha256_file(result_path),
                        'status': result['status'], 'chunk_count': len(result['chunks'])})
        print(canonical_json({'event': 'semantic_document_complete', 'source_id': record['source_id'], 'chunks': len(result['chunks'])}), flush=True)
    destination = folder / 'chunks.jsonl'
    destination.write_text(''.join(canonical_json(row)+'\n' for row in chunks), encoding='utf-8')
    atomic_json(folder/'manifest.json', {'parser_results_sha256': sha256_file(parser_results), 'model_identity': session.identity,
                                       'embedding_policy': session.policy, 'records': records, 'chunk_count': len(chunks)})
    return destination


def _legacy_expansion(snapshot: Path, engineering: Path, output: Path, session, cfg, *, resume: bool, options: dict) -> dict:
    """Predeclared engineering expansion; the old diagnostic never selects it."""
    folder = output/'legacy_expansion'
    folder.mkdir(exist_ok=True)
    base_rows = read_chunks(snapshot/'chunks.jsonl')
    manifest = json.loads((snapshot/'snapshot.json').read_text(encoding='utf-8'))
    if digest(base_rows) != manifest['chunks_sha256'] or sha256_file(snapshot/'cases.json') != manifest['cases_file_sha256']:
        raise ValueError('legacy snapshot hash mismatch')
    engineering_rows = load_candidate(engineering)['chunks']
    paths = {}
    for name, rows in [('legacy367_rebuilt', base_rows), ('legacy367_plus_engineering', base_rows+engineering_rows)]:
        path = folder/name
        if resume and (path/'manifest.json').exists():
            artifact = load_candidate(path)
            if artifact['manifest']['chunks_sha256'] != digest(rows) or artifact['manifest']['model_identity'] != session.identity:
                raise ValueError('expanded candidate resume identity mismatch')
        else:
            build_candidate(rows, path, embed_batch=session.documents, model_identity=session.identity,
                            embedding_policy=session.policy, chunk_strategy=name, batch_size=4, resume=resume)
        paths[name] = path
        print(canonical_json({'event': 'legacy_candidate_complete', 'candidate': name, 'chunks': len(rows)}), flush=True)
    runtimes = {name: CandidateRuntime(path, cfg=cfg, embed_query=session.query) for name, path in paths.items()}
    cases = _json_cases(snapshot/'cases.json')
    def progress(record):
        with (folder/'progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(canonical_json(record)+'\n')
        print(canonical_json({'event': 'legacy_case_complete', 'candidate': record['candidate'], 'case_id': record['case_id']}), flush=True)
    result = evaluate_candidates(runtimes, cases, top_k=5, search_options=options, comparison_mode='corpus_expansion', progress=progress)
    result['scope_note'] = 'Same current model/window policy/lexical v2 on legacy367 and its engineering expansion; not equal to historic production embeddings or ranking.'
    result['strategy_selection'] = 'engineering fixed before examining the old public diagnostic results; no test-driven search'
    before = {row['case_id']: row for row in result['results'] if row['candidate'] == 'legacy367_rebuilt'}
    after = {row['case_id']: row for row in result['results'] if row['candidate'] == 'legacy367_plus_engineering'}
    changes = []
    from services.retrieval_service.indexing.vnext_evaluation import case_metrics
    for case in cases:
        if case.get('corpus_scope') != 'legacy_protection':
            continue
        for mode in before[case['case_id']]['modes']:
            old = before[case['case_id']]['modes'][mode]['results']
            new = after[case['case_id']]['modes'][mode]['results']
            changes.append({'case_id': case['case_id'], 'mode': mode,
                            'before_at_3': case_metrics(case, old, 3), 'after_at_3': case_metrics(case, new, 3),
                            'before_at_5': case_metrics(case, old, 5), 'after_at_5': case_metrics(case, new, 5),
                            'top5_before': [r['chunk_id'] for r in old], 'top5_after': [r['chunk_id'] for r in new]})
    result['legacy_protection_changes'] = changes
    atomic_json(folder/'results.json', result)
    return {'results_file': str(folder/'results.json'), 'results_sha256': sha256_file(folder/'results.json'),
            'candidate_paths': {name: str(path) for name, path in paths.items()},
            'formal_metrics': result['formal_metrics'], 'production_activation_allowed': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['build', 'evaluate', 'experiment'])
    parser.add_argument('--chunks', type=Path, help='build: one structured chunks.jsonl')
    parser.add_argument('--chunk-strategy', default='specified')
    parser.add_argument('--candidate', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--parser-results', type=Path, help='experiment: parser results.json for one immutable source collection')
    parser.add_argument('--cases', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, help='existing local SentenceTransformer directory only')
    parser.add_argument('--embedding-cache', type=Path, help='optional reusable numeric cache, validated against model and policy identity')
    parser.add_argument('--query-vectors', type=Path, help='evaluate only: JSON query -> numeric vector, including production rewrites')
    parser.add_argument('--search-options', type=Path, help='frozen JSON: filters, RRF/MMR/pool configuration')
    parser.add_argument('--legacy-snapshot', type=Path, help='experiment: SELECT-only legacy chunks/cases snapshot for predeclared engineering expansion')
    parser.add_argument('--legacy-only', action='store_true', help='experiment: use --candidate engineering=PATH and run only the expansion stage')
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--comparison-mode', choices=['same_corpus', 'corpus_expansion'], default='same_corpus')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'build' and not args.legacy_only and not args.cases:
        parser.error('evaluation requires --cases')
    if args.command == 'build' and not args.chunks:
        parser.error('build requires --chunks')
    if args.command == 'experiment' and not args.legacy_only and not args.parser_results:
        parser.error('experiment requires --parser-results')
    if args.command == 'evaluate' and not args.candidate:
        parser.error('evaluate requires one or more --candidate NAME=PATH')
    if args.query_vectors and (args.model_dir or args.command != 'evaluate'):
        parser.error('--query-vectors is only for evaluate and cannot accompany --model-dir')
    if not args.model_dir and not args.query_vectors:
        parser.error('explicit --model-dir or --query-vectors is required; no implicit model downloads')
    if args.embedding_cache and not args.model_dir:
        parser.error('--embedding-cache requires an explicit local model')
    if args.legacy_snapshot and args.command != 'experiment':
        parser.error('--legacy-snapshot is only supported by experiment')
    if args.legacy_only and (args.command != 'experiment' or not args.model_dir or not args.legacy_snapshot
                            or len(args.candidate) != 1 or not args.candidate[0].startswith('engineering=')):
        parser.error('--legacy-only requires experiment, local model, legacy snapshot and exactly --candidate engineering=PATH')
    output = args.output_dir.resolve()
    if output.exists() and not args.resume:
        raise FileExistsError('output directory exists; use a new version or resume')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'results.json').exists():
        raise FileExistsError('completed evaluation is immutable')
    session = None
    started = perf_counter()
    if args.model_dir:
        from services.retrieval_service.indexing.vnext_model import LocalModelSession
        session = LocalModelSession(args.model_dir, args.embedding_cache or output/'embedding_cache')
        query_provider = session.query
        atomic_json(output/'model_loaded.json', session.report())
        print(canonical_json({'event': 'model_loaded', 'load_seconds': session.load_seconds}), flush=True)
    else:
        vectors = json.loads(args.query_vectors.read_text(encoding='utf-8'))
        def query_provider(query):
            if query not in vectors:
                raise ValueError(f'precomputed query vector is unavailable: {query}')
            return np.asarray(vectors[query], dtype=np.float32)
    if args.legacy_only:
        options = json.loads(args.search_options.read_text(encoding='utf-8')) if args.search_options else {}
        summary = _legacy_expansion(args.legacy_snapshot, Path(args.candidate[0].split('=', 1)[1]), output, session,
                                    load_config(), resume=args.resume, options=options)
        summary.update({'schema_version': 'thermal-vnext-expansion-run-v1', 'model': session.report(),
                        'elapsed_seconds': perf_counter()-started,
                        'scope': 'Continuation stage only; previously completed five-strategy results remain separate'})
        atomic_json(output/'results.json', summary)
        atomic_json(output/'evaluation_manifest.json', {'schema_version': 'thermal-vnext-experiment-manifest-v1',
                    'results_file': 'results.json', 'results_sha256': sha256_file(output/'results.json'),
                    'production_activation_allowed': False, 'rollback': 'Production unchanged; no activation occurred.'})
        return 0
    candidates = {}
    if args.command in {'build', 'experiment'}:
        if args.command == 'build':
            chunk_files = {args.chunk_strategy: args.chunks}
        else:
            base = args.parser_results.resolve().parent
            chunk_files = {name: base/name/'chunks.jsonl' for name in ('fixed', 'structure', 'parent_child', 'engineering')}
            chunk_files['semantic'] = _semantic_chunks(args.parser_results.resolve(), output, session, resume=args.resume)
        for name, chunks_path in chunk_files.items():
            records = load_chunk_inputs(chunks_path, name)
            path = output / 'candidates' / name
            if args.resume and (path/'manifest.json').exists():
                artifact = load_candidate(path)
                if artifact['manifest']['chunks_sha256'] != digest(records) or artifact['manifest']['model_identity'] != session.identity:
                    raise ValueError('completed resume candidate inputs differ')
                manifest = artifact['manifest']
            else:
                manifest = build_candidate(records, path, embed_batch=session.documents, model_identity=session.identity,
                                           embedding_policy=session.policy, chunk_strategy=name, batch_size=4,
                                           resume=args.resume)
            candidates[name] = path
            print(canonical_json({'event': 'candidate_complete', 'strategy': name, 'chunks': manifest['chunk_count'],
                                  'build_id': manifest['build_id']}), flush=True)
            atomic_json(output/'model_progress.json', session.report())
    else:
        for definition in args.candidate:
            name, separator, value = definition.partition('=')
            if not separator or not name or name in candidates:
                raise ValueError('candidate arguments must have unique NAME=PATH')
            candidates[name] = Path(value)
    if args.command == 'build':
        atomic_json(output/'build_summary.json', {'candidates': {name: str(path) for name, path in candidates.items()},
                                                'model': session.report(), 'production_activation_allowed': False})
        return 0
    cfg = load_config()
    # Record only retrieval configuration. Database credentials/LLM config are
    # never serialized or inspected by this experiment.
    configuration = {name: asdict(getattr(cfg, name)) if is_dataclass(getattr(cfg, name)) else vars(getattr(cfg, name))
                     for name in ('bm25', 'retrieval')}
    atomic_json(output/'retrieval_configuration.json', configuration)
    runtimes = {name: CandidateRuntime(path, cfg=cfg, embed_query=query_provider) for name, path in candidates.items()}
    options = json.loads(args.search_options.read_text(encoding='utf-8')) if args.search_options else {}
    def progress(record):
        with (output/'progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(canonical_json(record)+'\n')
        print(canonical_json({'event': 'case_complete', 'candidate': record['candidate'], 'case_id': record['case_id']}), flush=True)
    result = evaluate_candidates(runtimes, _json_cases(args.cases), top_k=args.top_k, search_options=options,
                                 progress=progress, comparison_mode=args.comparison_mode)
    result.update({'cases_file_sha256': sha256_file(args.cases), 'retrieval_configuration': configuration,
                   'elapsed_seconds': perf_counter()-started, 'model': session.report() if session else {'provider': 'precomputed_query_vectors',
                                                                                                     'file_sha256': sha256_file(args.query_vectors)},
                   'ablation_contract': {'original_hybrid': 'fixed candidate with unchanged production query/merge/rerank',
                                         'new_chunk_hybrid': 'same production algorithm on each alternative chunk candidate',
                                         'metadata_light_rerank': 'same artifacts with explicit filters and/or RRF/MMR/document cap',
                                         'production_index_activation': False}})
    result['review_filter_readiness'] = {name: {'reviewed_or_published_chunks': sum(row['review_status'] in {'reviewed', 'published'} for row in runtime.chunks),
                                               'total_chunks': len(runtime.chunks),
                                               'note': 'experiment includes machine drafts explicitly; review-only filtering can legitimately return zero'}
                                         for name, runtime in runtimes.items()}
    if args.legacy_snapshot:
        # Runtimes contain independent sparse corpora and source dictionaries.
        # The already-recorded ablation is complete: release those before
        # constructing the two additional expansion runtimes in this process.
        import gc
        del runtimes
        gc.collect()
        result['legacy_expansion'] = _legacy_expansion(args.legacy_snapshot, candidates['engineering'], output, session, cfg,
                                                     resume=args.resume, options=options)
        result['model'] = session.report()
        result['elapsed_seconds'] = perf_counter()-started
    atomic_json(output/'results.json', result)
    atomic_json(output/'evaluation_manifest.json', {
        'schema_version': 'thermal-vnext-experiment-manifest-v1',
        'candidates': result['candidate_manifests'], 'cases_file_sha256': result['cases_file_sha256'],
        'results_file': 'results.json', 'results_sha256': sha256_file(output/'results.json'),
        'source_collection_version': result['source_collection_version'],
        'search_configuration_sha256': result['search_configuration_sha256'],
        'production_activation_allowed': False,
        'release_blockers': result['release_blockers'],
        'rollback': 'No active pointer, production index, or database was changed. Keep using the existing production generation.',
        'immutable_candidates': 'Evaluation linkage is stored here; completed candidate artifacts are not rewritten.'})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
