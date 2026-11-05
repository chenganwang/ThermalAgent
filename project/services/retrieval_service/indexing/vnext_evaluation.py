"""Reproducible retrieval diagnostics with explicit label provenance.

Machine references are useful development probes, never independent gold.
Source-span labels are strategy independent; source-only labels have a separate
document granularity. No result from this module can activate production.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from statistics import mean
from typing import Any

import numpy as np

from .vnext_artifacts import digest

EVALUATION_VERSION = 'thermal-vnext-evaluation-v1'


def recover_completed_records(artifacts: dict, cases: list[dict], records: list[dict], *, top_k: int = 5,
                              search_options: dict | None = None, comparison_mode: str = 'same_corpus') -> dict:
    """Aggregate complete recorded searches after checking all original evidence.

    This performs no retrieval and cannot recover a missing search. Artifact
    files must already have passed ``load_candidate`` hash verification. Scores
    and timings are preserved observations, not newly measured performance.
    """
    from copy import deepcopy
    normalized = validate_cases(cases)
    expected = {(name, case['case_id']) for name in artifacts for case in normalized}
    observed = {(row.get('candidate'), row.get('case_id')) for row in records}
    if len(observed) != len(records) or observed != expected:
        raise ValueError('recorded searches must cover every candidate/case exactly once')
    case_by_id = {case['case_id']: case for case in normalized}
    modes_expected = {'bm25_only', 'dense_only', 'original_hybrid', 'rrf', 'rrf_mmr'}
    evidence_fields = ('source_id', 'text', 'page_start', 'page_end', 'section_path', 'document_sha256',
                       'content_sha256', 'source_spans', 'parent_id', 'parent_context', 'context',
                       'review_status', 'quality_flags')
    indexed = {name: {row['chunk_id']: row for row in artifact['chunks']} for name, artifact in artifacts.items()}
    lookup = {}
    for record in records:
        name, identity = record['candidate'], record['case_id']
        case = case_by_id[identity]
        if any(record.get(field) != case.get(field) for field in ('query', 'split', 'label_status', 'category', 'corpus_scope')):
            raise ValueError('recorded query/label provenance differs from frozen cases')
        if set(record.get('modes', {})) != modes_expected:
            raise ValueError('incomplete recorded ablations')
        for mode in record['modes'].values():
            rows = mode['results']
            if len(rows) > top_k or len({row['chunk_id'] for row in rows}) != len(rows):
                raise ValueError('invalid recorded result count or duplicate hits')
            if not np.isfinite(mode['latency_ms']) or mode['latency_ms'] < 0:
                raise ValueError('invalid recorded timing')
            for rank, row in enumerate(rows, 1):
                original = indexed[name].get(row['chunk_id'])
                if (not original or row['rank'] != rank or not np.isfinite(row['score'])
                        or any(row.get(field) != original.get(field) for field in evidence_fields)):
                    raise ValueError('recorded result differs from immutable candidate evidence')
            if mode.get('metrics') != case_metrics(case, rows, top_k):
                raise ValueError('recorded metrics differ from frozen labels')
            configuration = mode.get('configuration')
            if configuration and configuration != {**{'rank_constant': 60, 'mmr_lambda': .75,
                                                       'max_per_document': 1, 'pool_size': 50, 'top_k': top_k},
                                                    **{k: v for k, v in (search_options or {}).items() if k != 'filters'}}:
                raise ValueError('recorded search configuration differs')
            if mode.get('filters', {}) != (search_options or {}).get('filters', {}):
                raise ValueError('recorded metadata filters differ')
        lookup[(name, record['query'])] = record['modes']

    class RecordedRuntime:
        def __init__(self, name, artifact):
            self.name, self.artifact, self.chunks = name, artifact, artifact['chunks']

        def search(self, query, **kwargs):
            return deepcopy(lookup[(self.name, query)])

    result = evaluate_candidates({name: RecordedRuntime(name, artifact) for name, artifact in artifacts.items()},
                                 cases, top_k=top_k, search_options=search_options, comparison_mode=comparison_mode)
    result['recovery'] = {'status': 'complete_recorded_searches_revalidated', 'retrieval_executed_during_recovery': False,
                          'validated': ['complete Cartesian case coverage', 'unique candidate/case pairs', 'frozen query/labels',
                                        'all returned source text and provenance', 'recomputed per-case metrics', 'search configuration'],
                          'timing_scope': 'preserved original recorded observations; aggregation time is not retrieval time'}
    return result


def validate_cases(cases: list[dict]) -> list[dict]:
    if not isinstance(cases, list) or not cases:
        raise ValueError('evaluation requires a nonempty list of cases')
    # Adapter fields are retained, and normalized only in memory; input files
    # and their recorded hashes remain unchanged.
    cases = [dict(case) if isinstance(case, dict) else case for case in cases]
    ids, queries = set(), {}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('case must be an object')
        if 'relevant_spans' in case:
            if 'relevant_evidence' in case and case['relevant_evidence'] != case['relevant_spans']:
                raise ValueError('conflicting relevant_spans/relevant_evidence labels')
            case['relevant_evidence'] = case['relevant_spans']
        if 'is_negative' in case:
            if type(case['is_negative']) is not bool:
                raise ValueError('is_negative must be boolean')
            if 'answerable' in case and case['answerable'] == case['is_negative']:
                raise ValueError('conflicting negative/answerable labels')
            case['answerable'] = not case['is_negative']
        identity, query = case.get('case_id'), case.get('query')
        if not isinstance(identity, str) or not identity.strip() or identity in ids:
            raise ValueError('case_id must be a unique nonempty string')
        if not isinstance(query, str) or not query.strip():
            raise ValueError('case query must be nonempty')
        ids.add(identity)
        split = case.get('split')
        if split not in {'development', 'validation', 'test'}:
            raise ValueError('case must declare development/validation/test split')
        normalized = re.sub(r'\s+', ' ', query).strip().casefold()
        if normalized in queries and queries[normalized] != split:
            raise ValueError('query leakage across development/validation/test splits')
        queries[normalized] = split
        status = case.get('label_status')
        if status not in {'machine_reference', 'human_reviewed', 'unlabeled'}:
            raise ValueError('unknown case label_status')
        if status == 'human_reviewed':
            review = case.get('review') or {}
            if not all(isinstance(review.get(k), str) and review[k].strip() for k in ('reviewer_id', 'reviewed_at', 'protocol_version')):
                raise ValueError('human labels require explicit reviewer/time/protocol provenance')
            try:
                datetime.fromisoformat(review['reviewed_at'].replace('Z', '+00:00'))
            except ValueError as error:
                raise ValueError('reviewed_at must be ISO-8601') from error
        for key in ('relevant_chunk_ids', 'acceptable_chunk_ids', 'relevant_source_ids', 'forbidden_source_ids'):
            if key in case and (not isinstance(case[key], list) or not all(isinstance(v, str) and v for v in case[key])):
                raise ValueError(f'{key} must be a string array')
        evidence = case.get('relevant_evidence', [])
        if not isinstance(evidence, list):
            raise ValueError('relevant_evidence must be an array')
        for span in evidence:
            if not isinstance(span, dict) or not all(isinstance(span.get(k), str) and span[k] for k in ('source_id', 'block_id')):
                raise ValueError('evidence requires source_id and block_id')
            if 'start' in span or 'end' in span:
                if type(span.get('start')) is not int or type(span.get('end')) is not int or not 0 <= span['start'] < span['end']:
                    raise ValueError('evidence span offsets must be ordered nonnegative integers')
        if 'answerable' in case and type(case['answerable']) is not bool:
            raise ValueError('answerable must be an explicit boolean')
        if case.get('answerable') is False and (evidence or case.get('relevant_chunk_ids') or case.get('relevant_source_ids')):
            raise ValueError('unanswerable case cannot also declare relevant evidence')
    return cases


def _label_set(case: dict) -> tuple[str, list]:
    if case.get('relevant_evidence'):
        # Identical repeated labels cannot artificially inflate the denominator.
        labels = {digest(value): value for value in case['relevant_evidence']}
        return 'source_block_span', list(labels.values())
    if case.get('relevant_chunk_ids'):
        return 'chunk_id', sorted(set(case['relevant_chunk_ids']))
    if case.get('relevant_source_ids'):
        return 'source_document', sorted(set(case['relevant_source_ids']))
    return 'unlabeled', []


def _matches(result: dict, label: Any, granularity: str) -> bool:
    if granularity == 'chunk_id':
        return result['chunk_id'] == label
    if granularity == 'source_document':
        return result['source_id'] == label
    if result['source_id'] != label['source_id']:
        return False
    for span in result.get('source_spans', []):
        if span['block_id'] != label['block_id']:
            continue
        if 'start' not in label:
            return True
        overlap = max(0, min(span['end'], label['end']) - max(span['start'], label['start']))
        # Predeclared 50% coverage of the reference span; no semantic judgment.
        if overlap / (label['end'] - label['start']) >= .5:
            return True
    return False


def case_metrics(case: dict, results: list[dict], top_k: int) -> dict:
    selected = results[:top_k]
    granularity, labels = _label_set(case)
    matches = [[_matches(result, label, granularity) for label in labels] for result in selected]
    relevant_ranks = [rank for rank, row in enumerate(matches, 1) if any(row)]
    found = {i for row in matches for i, hit in enumerate(row) if hit}
    forbidden = set(case.get('forbidden_source_ids') or [])
    document_labels = set(case.get('relevant_source_ids') or [])
    acceptable = set(case.get('acceptable_chunk_ids') or []) | set(case.get('relevant_chunk_ids') or [])
    labeled = bool(labels) and case.get('label_status') != 'unlabeled'
    return {
        'label_granularity': granularity, 'label_status': case['label_status'], 'k': top_k,
        'relevant_count': len(labels), 'returned_count': len(selected), 'found_relevant_count': len(found),
        'hit_at_k': int(bool(relevant_ranks)) if labeled else None,
        'recall_at_k': len(found)/len(labels) if labeled else None,
        'reciprocal_rank': 1/relevant_ranks[0] if relevant_ranks and labeled else 0. if labeled else None,
        'precision_at_k': len(relevant_ranks)/top_k if labeled else None,
        'precision_returned': len(relevant_ranks)/len(selected) if labeled and selected else 0. if labeled else None,
        'unanswerable_return_rate': int(bool(selected)) if case.get('answerable') is False and case['label_status'] != 'unlabeled' else None,
        'forbidden_source_return_rate': int(any(row['source_id'] in forbidden for row in selected)) if forbidden else None,
        'document_hit_at_k': int(any(row['source_id'] in document_labels for row in selected)) if document_labels and case['label_status'] != 'unlabeled' else None,
        'acceptable_chunk_hit_at_k': int(any(row['chunk_id'] in acceptable for row in selected)) if acceptable and case['label_status'] != 'unlabeled' else None,
        'artifact_provenance_complete_rate': mean(bool(row.get('document_sha256') and row.get('source_spans') and row.get('page_start')) for row in selected) if selected else None,
        'provenance_scope': 'local artifact fields present; not source correctness, citation entailment, or expert evidence support',
    }


def _aggregate(rows: list[dict]) -> dict:
    metrics = ('hit_at_k', 'recall_at_k', 'reciprocal_rank', 'precision_at_k', 'precision_returned',
               'unanswerable_return_rate', 'forbidden_source_return_rate', 'document_hit_at_k',
               'acceptable_chunk_hit_at_k', 'artifact_provenance_complete_rate')
    result = {'case_count': len(rows)}
    for name in metrics:
        values = [row['metrics'][name] for row in rows if row['metrics'][name] is not None]
        result[name] = {'value': mean(values) if values else None, 'denominator': len(values),
                        'status': 'available' if values else 'unavailable', 'aggregation': 'macro_case_mean'}
    latency = [row['latency_ms'] for row in rows]
    result['latency_ms'] = {'p50': float(np.percentile(latency, 50)), 'p95': float(np.percentile(latency, 95)),
                            'mean': mean(latency), 'sample_count': len(latency),
                            'scope': 'sequential ablations, shared warm query cache; not cold-start/concurrent SLA'}
    return result


def evaluate_candidates(runtimes: dict, cases: list[dict], *, top_k: int = 5,
                        search_options: dict | None = None, progress=None, comparison_mode: str = 'same_corpus') -> dict:
    original_cases_sha256 = digest(cases)
    cases = validate_cases(cases)
    if not runtimes or type(top_k) is not int or top_k < 1:
        raise ValueError('nonempty runtimes and positive integer top_k required')
    source_versions = {rt.artifact['manifest']['source_collection_version'] for rt in runtimes.values()}
    source_documents = {digest(rt.artifact['manifest']['source_documents']) for rt in runtimes.values()}
    if comparison_mode == 'same_corpus':
        if len(source_versions) != 1 or len(source_documents) != 1:
            raise ValueError('same-corpus comparison requires identical source collections')
    elif comparison_mode == 'corpus_expansion':
        if len(runtimes) != 2:
            raise ValueError('corpus expansion compares exactly a base and its superset')
        sets = sorted([set(map(tuple, rt.artifact['manifest']['source_documents'])) for rt in runtimes.values()], key=len)
        if not sets[0] < sets[1]:
            raise ValueError('expanded corpus must strictly contain the unchanged base source versions')
        chunk_sets = sorted([set(row['chunk_id'] for row in rt.chunks) for rt in runtimes.values()], key=len)
        if not chunk_sets[0] < chunk_sets[1]:
            raise ValueError('expanded corpus must preserve every base chunk ID')
        base, expanded = sorted(runtimes.values(), key=lambda runtime: len(runtime.chunks))
        expanded_rows = {row['chunk_id']: row for row in expanded.chunks}
        if any(row != expanded_rows[row['chunk_id']] for row in base.chunks):
            raise ValueError('corpus expansion changed the base chunk content/provenance')
    else:
        raise ValueError('unknown corpus comparison mode')
    embedding_contracts = {digest({key: rt.artifact['manifest'][key] for key in ('model_identity', 'embedding_policy', 'tokenizer_version')}) for rt in runtimes.values()}
    if len(embedding_contracts) != 1:
        raise ValueError('ablation requires the same embedding/lexical contract across candidate strategies')
    search_options = search_options or {}
    results, groups, formal_groups, categories, scopes = [], defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for name, runtime in runtimes.items():
        for case in cases:
            modes = runtime.search(case['query'], top_k=top_k, **search_options)
            independent = (case['label_status'] == 'human_reviewed' and case.get('independent_gold') is True
                           and case['split'] == 'test' and case.get('used_for_tuning') is False)
            for mode_name, mode in modes.items():
                mode['metrics'] = case_metrics(case, mode['results'], top_k)
                key = (name, mode_name, case['split'], case['label_status'], mode['metrics']['label_granularity'])
                groups[key].append(mode)
                categories[(name, mode_name, case.get('category') or 'unspecified')].append(mode)
                scopes[(name, mode_name, case.get('corpus_scope') or 'unspecified')].append(mode)
                if independent:
                    formal_groups[(name, mode_name, mode['metrics']['label_granularity'])].append(mode)
            record = {'candidate': name, 'case_id': case['case_id'], 'query': case['query'],
                      'split': case['split'], 'label_status': case['label_status'], 'independent_gold_eligible': independent,
                      'category': case.get('category'), 'corpus_scope': case.get('corpus_scope'),
                      'label_coverage': {'expected_sources_in_candidate': sorted(set(case.get('relevant_source_ids') or []) & {r['source_id'] for r in runtime.chunks}),
                                         'expected_sources_missing_from_candidate': sorted(set(case.get('relevant_source_ids') or []) - {r['source_id'] for r in runtime.chunks})},
                      'modes': modes}
            results.append(record)
            if progress:
                progress(record)
    gold_count = sum(case['label_status'] == 'human_reviewed' and case.get('independent_gold') is True
                     and case['split'] == 'test' and case.get('used_for_tuning') is False for case in cases)
    positive_gold_count = sum(case['label_status'] == 'human_reviewed' and case.get('independent_gold') is True
                             and case['split'] == 'test' and case.get('used_for_tuning') is False and bool(_label_set(case)[1]) for case in cases)
    return {'schema_version': EVALUATION_VERSION, 'created_at': datetime.now(timezone.utc).isoformat(),
            'cases_sha256': original_cases_sha256, 'normalized_cases_sha256': digest(cases), 'case_count': len(cases), 'top_k': top_k,
            'search_configuration': search_options, 'search_configuration_sha256': digest(search_options),
            'candidate_manifests': {name: {'build_id': rt.artifact['manifest']['build_id'],
                                          'manifest_sha256': digest(rt.artifact['manifest']),
                                          'path': str(rt.artifact['path']),
                                          'chunk_strategy': rt.artifact['manifest']['chunk_strategy']} for name, rt in runtimes.items()},
            'comparison_mode': comparison_mode,
            'source_collection_version': next(iter(source_versions)) if len(source_versions) == 1 else None,
            'source_collection_versions': {name: runtime.artifact['manifest']['source_collection_version'] for name, runtime in runtimes.items()},
            'metric_contract': {'recall': 'unique labeled evidence units found / all relevant labeled units',
                                'precision_at_k': 'relevant returned chunks / requested k, including unfilled slots',
                                'source_span_match': 'same source+block and >=50% coverage of reference span; no semantic claim',
                                'negative_return': 'any retrieval result for an explicitly unanswerable case; not answer hallucination',
                                'machine_references': 'development diagnostics only; not independent gold'},
            'summary': [{'candidate': key[0], 'mode': key[1], 'split': key[2], 'label_status': key[3],
                         'label_granularity': key[4], **_aggregate(rows)} for key, rows in sorted(groups.items())],
            'by_category': [{'candidate': key[0], 'mode': key[1], 'category': key[2], **_aggregate(rows)} for key, rows in sorted(categories.items())],
            'by_corpus_scope': [{'candidate': key[0], 'mode': key[1], 'corpus_scope': key[2], **_aggregate(rows)} for key, rows in sorted(scopes.items())],
            'formal_metrics': {'independent_gold_case_count': gold_count,
                               'top5_hit_rate': {'status': 'available' if positive_gold_count and top_k == 5 else 'unavailable',
                                                'reason': None if positive_gold_count and top_k == 5 else 'independent unused human test positive gold at k=5 is required'},
                               'by_candidate_mode': [{'candidate': key[0], 'mode': key[1], 'label_granularity': key[2],
                                                      **_aggregate(rows)} for key, rows in sorted(formal_groups.items())]},
            'production_activation_allowed': False,
            'release_blockers': ['candidate-only workflow; explicit activation not implemented',
                                 'independent human relevance/evidence/source review and non-regression release gates required'],
            'results': results}
