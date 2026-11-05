"""Versioned, source-preserving contracts for unreviewed knowledge candidates.

This layer does not grant the legacy writer's ``accepted`` status. Automatic
checks establish identity/location only; engineering review is a separate event.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 'open-knowledge-staging-v1'
STATES = ('machine_draft', 'pending_review', 'reviewed', 'published')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def normalized_claim(text: str) -> str:
    # Case, mathematical signs and unit prefixes are evidence. Never apply the
    # legacy slug normalizer to the original claim or numerical conflict key.
    return re.sub(r'\s+', ' ', str(text)).strip()


def validate_candidate(candidate: dict, sources: dict[str, dict], blocks: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    for key in ('candidate_id', 'version_id', 'claim', 'unit_type', 'domain_tags', 'evidence', 'automatic_checks', 'review_status'):
        if not candidate.get(key):
            errors.append(f'missing:{key}')
    if candidate.get('review_status') not in STATES:
        errors.append('unknown_review_state')
    if candidate.get('human_reviewed') is not False:
        errors.append('automatic_candidate_cannot_claim_human_review')
    evidence = candidate.get('evidence', [])
    for ev in evidence:
        source = sources.get(ev.get('source_id'))
        block = blocks.get(ev.get('block_id'))
        if not source or not block:
            errors.append('unknown_source_or_block')
            continue
        if ev.get('document_sha256') != source.get('sha256'):
            errors.append('source_hash_mismatch')
        if ev.get('source_id') != block.get('source_id'):
            errors.append('block_source_mismatch')
        if not isinstance(ev.get('page'), int) or isinstance(ev['page'], bool) or ev['page'] < 1:
            errors.append('invalid_page')
        elif ev['page'] != block.get('page'):
            errors.append('page_mismatch')
        text = str(block.get('text', ''))
        start, end = ev.get('start'), ev.get('end')
        if (not isinstance(start, int) or isinstance(start, bool) or
                not isinstance(end, int) or isinstance(end, bool) or not 0 <= start < end <= len(text)):
            errors.append('invalid_evidence_span')
        elif text[start:end] != candidate.get('claim'):
            errors.append('claim_not_exact_source_span')
        if not (source.get('license') or {}).get('allow_fulltext'):
            errors.append('fulltext_permission_not_recorded')
    claim_digest = content_hash(normalized_claim(candidate.get('claim', '')))
    if candidate.get('claim_sha256') != claim_digest:
        errors.append('claim_hash_mismatch')
    return sorted(set(errors))


def validate_human_review(review: dict, candidate: dict, *, record_id: str) -> list[str]:
    """Validate an externally supplied attestation; never infer who reviewed it."""
    errors = []
    if review.get('record_id') != record_id:
        errors.append('review_record_identity_mismatch')
    if review.get('origin') != 'human' or review.get('decision') not in {'accepted', 'rejected', 'needs_edit'}:
        errors.append('explicit_human_decision_required')
    if not all(isinstance(review.get(k), str) and review[k].strip() for k in ('reviewer', 'reviewed_at', 'rationale')):
        errors.append('reviewer_timestamp_rationale_required')
    if review.get('candidate_id') != candidate.get('candidate_id') or review.get('version_id') != candidate.get('version_id'):
        errors.append('review_version_mismatch')
    if review.get('claim_sha256') != candidate.get('claim_sha256'):
        errors.append('review_content_mismatch')
    if review.get('independent_of_generator') is not True or review.get('domain_expertise_confirmed') is not True:
        errors.append('independent_domain_review_required')
    try:
        parsed = datetime.fromisoformat(str(review.get('reviewed_at', '')).replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
            errors.append('invalid_review_timestamp')
    except ValueError:
        errors.append('invalid_review_timestamp')
    return errors
