"""Evidence-bound draft questions; no automatic promotion to independent gold."""
from __future__ import annotations

import re
from .staging_contracts import content_hash, normalized_claim

CATEGORIES = {'knowledge', 'formula_parameters', 'design_comparison', 'engineering_figure',
              'fault_diagnosis', 'multiple_constraints', 'physical_applicability', 'insufficient_evidence'}
SPLITS = {'development', 'validation', 'test'}


def query_key(text: str) -> str:
    return re.sub(r'\W+', '', text.casefold())


def build_questions(seeds: list[dict], documents: list[dict], sources: list[dict], *, existing_queries=()) -> dict:
    """Bind human-readable seed proposals to actual extracted blocks.

    Anchors select exact text only. They establish a reproducible location,
    not semantic entailment. Answers and labels remain machine proposals.
    """
    by_source = {s['source_id']: s for s in sources}
    blocks = {d['document']['source_id']: d['blocks'] for d in documents}
    prior = {query_key(q) for q in existing_queries}
    seen = set(prior)
    questions, rejected = [], []
    for seed in seeds:
        errors = []
        query = seed.get('query', '').strip()
        key = query_key(query)
        if not key or key in seen:
            errors.append('duplicate_or_missing_query')
        seen.add(key)
        spans = []
        for anchor in seed.get('anchors', []):
            sid, phrase = anchor['source_id'], anchor['text']
            matches = [b for b in blocks.get(sid, []) if normalized_claim(phrase).casefold() in normalized_claim(b['text']).casefold()]
            if anchor.get('page'):
                matches = [b for b in matches if b['page'] == anchor['page']]
            if not matches:
                errors.append('anchor_missing:' + sid + ':' + phrase)
                continue
            # Preserve the entire smallest matching original block. Word
            # offsets into whitespace-normalized text must never be treated as
            # offsets into raw extraction.
            block = min(matches, key=lambda b: (len(b['text']), b['page'], b['block_id']))
            spans.append({'source_id': sid, 'document_sha256': by_source[sid]['sha256'],
                          'block_id': block['block_id'], 'page': block['page'],
                          'start': 0, 'end': len(block['text']), 'text': block['text'],
                          'bbox': block.get('bbox'), 'source_url': by_source[sid]['url']})
        if not seed.get('is_negative', False) and not spans:
            errors.append('positive_question_requires_source_evidence')
        if errors:
            rejected.append({'case_id': seed.get('case_id'), 'errors': errors})
            continue
        item = {k: v for k, v in seed.items() if k != 'anchors'}
        item.update({'query': query, 'relevant_spans': spans,
                     'relevant_source_ids': sorted({s['source_id'] for s in spans}),
                     'label_status': 'machine_reference', 'review_status': 'pending_review',
                     'human_reviewed': False, 'independent_gold': False,
                     'reference_origin': 'machine-authored proposal based on identified source text',
                     'automatic_checks': {'exact_source_location': True, 'duplicate_query': False,
                                          'semantic_support': 'requires_expert_review',
                                          'label_correctness': 'requires_expert_review'},
                     'prior_30_dataset_overlap': 'exact normalized query excluded; semantic duplicates require review'})
        item['version_id'] = content_hash(item)
        questions.append(item)
    return {'schema_version': 'coolingqa-candidate-v1', 'questions': questions, 'rejected': rejected,
            'summary': {'candidate_count': len(questions), 'human_reviewed_increment': 0,
                        'formal_80_question_acceptance': 'unavailable',
                        'split_semantics': 'reserved machine partitions; test is not independent human gold',
                        'by_category': {c: sum(q['category'] == c for q in questions) for c in sorted(CATEGORIES)}}}


def validate_questions(questions: list[dict], sources: dict, blocks: dict) -> list[str]:
    errors, identifiers, queries = [], set(), set()
    for q in questions:
        cid = q.get('case_id')
        if not isinstance(cid, str) or not cid or cid in identifiers:
            errors.append('case_id_missing_or_duplicate')
        identifiers.add(cid)
        key = query_key(q.get('query', ''))
        if not key or key in queries:
            errors.append('query_missing_or_duplicate')
        queries.add(key)
        if q.get('category') not in CATEGORIES or q.get('split') not in SPLITS:
            errors.append('category_or_split_invalid')
        if q.get('label_status') != 'machine_reference' or q.get('human_reviewed') is not False or q.get('independent_gold') is not False:
            errors.append('candidate_cannot_self_award_gold')
        if not q.get('reference_answer') or any(k not in q for k in ('expected_parameters', 'expected_tools', 'figure_labels', 'cause_labels')):
            errors.append('answer_or_expected_labels_missing')
        spans = q.get('relevant_spans', [])
        if q.get('is_negative', False):
            if spans or q.get('relevant_source_ids') or q.get('expected_action') != 'abstain_and_request_evidence':
                errors.append('negative_case_contract_invalid')
        elif not spans:
            errors.append('positive_evidence_missing')
        if set(q.get('relevant_source_ids', [])) != {s.get('source_id') for s in spans}:
            errors.append('source_set_mismatch')
        for span in spans:
            source = sources.get(span.get('source_id'))
            block = blocks.get(span.get('block_id'))
            if not source or not block or block['source_id'] != span.get('source_id') or source['sha256'] != span.get('document_sha256') or block['page'] != span.get('page'):
                errors.append('evidence_location_mismatch')
                continue
            a, b = span.get('start'), span.get('end')
            if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(block['text']) or block['text'][a:b] != span.get('text'):
                errors.append('evidence_text_mismatch')
        if content_hash({k: v for k, v in q.items() if k != 'version_id'}) != q.get('version_id'):
            errors.append('question_version_mismatch')
    return sorted(set(errors))
