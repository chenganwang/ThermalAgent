"""Extract coherent, verbatim engineering statements without fabricating review.

Structured blocks, not arbitrary character windows, are the candidate unit.
Existing formula recognizers supply explicitly machine-generated annotations.
"""
from __future__ import annotations

import re
from collections import Counter
from .formula_extractor import extract as recognize_formulas
from .staging_contracts import SCHEMA_VERSION, content_hash, normalized_claim, validate_candidate

DOMAIN_TERMS = {
    'chip_thermal_design': r'junction|thermal resistance|thermal interface|contact resistance|heat spread|hot.?spot|chip|semiconductor|结温|热阻|芯片|接触热阻|封装',
    'liquid_cooling': r'cold plate|coolant|microchannel|liquid cooling|pressure drop|pumping|hydraulic|glycol|heat exchanger|冷板|冷却液|液冷|压降|微通道|换热器',
    'coolant_properties': r'viscosity|thermal conductivity|water.{0,25}(density|enthalpy|heat capacity)|density.{0,25}water|黏度|粘度|水.{0,10}物性|比热|导热率',
    'engineering_validation': r'uncertainty|calibration|measurement error|energy balance|conservation|boundary condition|validation|不确定度|测量误差|守恒|边界条件',
    'cooling_diagnostics': r'blockage|fouling|corrosion|leakage|low flow|cavitation|air lock|堵塞|泄漏|腐蚀|气蚀|流量不足',
}
_PROPOSITION = re.compile(r'\b(is|are|has|have|depends|increases|decreases|requires|should|must|can|shall|causes|defined|determined|results|due to|measured|calculated|estimated|uncertainty)\b|是|应|须|导致|取决|用于|随着|定义|关系|通过|不确定|测量|计算', re.I)
_REFERENCE = re.compile(r'^\s*(references?|bibliography|contents|copyright|acknowledg|参考文献)|https?://|doi:', re.I)
_PUBLICATION = re.compile(r'\b(preface|foreword|ad hoc committee|positive reception|copies were distributed|first printing|second printing|appointed|we hope|we thank|acknowledgments?)\b|前言|致谢|编委|出版说明', re.I)
_SUBSTANCE = re.compile(r'\b(temperature|pressure|density|viscosity|conductivity|flow|heat|boundary|covariance|correlation|standard deviation|type [ab]|probability|distribution|correction|coverage|measurand|calibration|degrees of freedom|confidence interval|root.sum.of.squares)\b|温度|压力|流量|密度|协方差|标准差|概率|校准|修正|置信|覆盖因子', re.I)
_CONDITION = re.compile(r'\b(if|when|under|assuming|assume|steady|laminar|turbulent|single.phase|only|limited|provided|unless|range)\b|条件|稳态|层流|湍流|单相|假设|仅|范围', re.I)
_UNIT = re.compile(r'(?<![A-Za-z])(?:[kMmun]?W/(?:m[·*]?K|m²|m2)|[kMmun]?W|[kM]?Pa|K/W|°C|℃|kg/s|L/min|kg/m[³3]|J/\(?kg[·*]?K\)?|m[²³]|mm|K)(?![A-Za-z])')


def _type(text: str, kind: str) -> str:
    if kind == 'table':
        return 'parameter'
    if re.search(r'\w\s*=|[Δθρμ]\s*=', text):
        return 'formula'
    if re.search(DOMAIN_TERMS['cooling_diagnostics'], text, re.I):
        return 'fault_case'
    return 'concept'


def build_candidates(documents: list[dict], source_records: list[dict]) -> dict:
    sources = {s['source_id']: s for s in source_records}
    blocks: dict[str, dict] = {}
    candidates: dict[str, dict] = {}
    rejected = []
    for document in documents:
        meta = document.get('document', {})
        sid = meta.get('source_id')
        source = sources.get(sid, {})
        for raw in document.get('blocks', []):
            block = {**raw, 'source_id': sid}
            bid = block.get('block_id')
            if bid in blocks and blocks[bid] != block:
                raise ValueError('block_identity_collision')
            blocks[bid] = block
            text = str(block.get('text') or '')
            flags = list(block.get('quality_flags', []))
            kind = str(block.get('kind', 'paragraph'))
            reason = None
            tags = [name for name, pat in DOMAIN_TERMS.items() if re.search(pat, text, re.I)]
            if kind in {'header', 'footer', 'heading', 'page_number', 'image', 'caption'}:
                reason = 'not_standalone_engineering_statement'
            elif len(normalized_claim(text)) < 100 or len(text) > 6000:
                reason = 'insufficient_or_overlong_context'
            elif not tags or (not _PROPOSITION.search(text) and kind not in {'formula', 'table'}):
                reason = 'no_scoped_engineering_proposition'
            elif _REFERENCE.search(text):
                reason = 'reference_or_link_block'
            elif _PUBLICATION.search(text):
                reason = 'administrative_or_publication_boilerplate'
            elif tags == ['engineering_validation'] and not _SUBSTANCE.search(text):
                reason = 'no_technical_uncertainty_statement'
            elif block.get('exclude_from_retrieval') or any('repeated_' in f or 'garbled' in f or f in {'replacement_or_control_character', 'two_column_unresolved'} for f in flags):
                reason = 'parser_quality_exclusion'
            elif not source or meta.get('sha256') != source.get('sha256'):
                reason = 'source_version_mismatch'
            elif not (source.get('license') or {}).get('allow_fulltext'):
                reason = 'fulltext_permission_not_recorded'
            if reason:
                rejected.append({'source_id': sid, 'block_id': bid, 'reason': reason})
                continue
            normalized = normalized_claim(text)
            digest = content_hash(normalized)
            ev = {'source_id': sid, 'document_sha256': source['sha256'], 'url': source.get('url'),
                  'block_id': bid, 'page': block.get('page'), 'bbox': block.get('bbox'),
                  'start': 0, 'end': len(text), 'section_path': block.get('section_path', []),
                  'license': source.get('license', {}),
                  'attribution': {'title': source.get('title'), 'publisher': source.get('publisher'), 'authors': source.get('authors', [])}}
            # Exact duplicates with different whitespace retain each source's
            # exact claim as a version, not a false same-span assertion.
            version = content_hash({'claim': text, 'source_id': sid, 'document_sha256': source['sha256'], 'block_id': bid})
            key = 'ku_' + digest[:24]
            if key in candidates and candidates[key]['claim'] == text:
                candidates[key]['evidence'].append(ev)
                continue
            if key in candidates:
                key += '_' + version[:8]
            annotations = [f.to_dict() for f in recognize_formulas(text, {'source_text_preview': text[:300]})]
            item = {'schema_version': SCHEMA_VERSION, 'candidate_id': key, 'version_id': version,
                    'claim': text, 'claim_sha256': digest, 'title': normalized[:110],
                    'unit_type': _type(text, kind), 'domain_tags': tags, 'evidence': [ev],
                    'conditions': {'status': 'explicit_markers_present' if _CONDITION.search(text) else 'not_extracted_needs_review',
                                   'source_block_id': bid, 'automatic_generalization_allowed': False},
                    'formula_annotations': annotations, 'unit_tokens': sorted(set(_UNIT.findall(text))),
                    'annotation_origin': 'machine_rule_annotations_not_source_transcription',
                    'licensing_note': 'Quoted source text retains its source license and attribution; software license does not relicense it.',
                    'related_candidate_ids': [], 'possible_duplicate_ids': [], 'possible_conflict_ids': [],
                    'review_status': 'machine_draft', 'human_reviewed': False,
                    'automatic_checks': {'source_identity': True, 'exact_source_span': True, 'formula_check': 'pattern_only_not_dimensional_validation' if annotations else 'not_applicable_or_unrecognized',
                                         'unit_check': 'token_recognition_only_not_physical_validation', 'domain_review': 'unavailable'},
                    'quality_flags': sorted(set(flags + ['requires_energy_domain_review'] + (['formula_or_table_needs_visual_check'] if kind in {'formula', 'table'} else [])))}
            errors = validate_candidate(item, sources, blocks)
            if errors:
                rejected.append({'source_id': sid, 'block_id': bid, 'reason': 'contract_failed', 'errors': errors})
            else:
                candidates[key] = item
    rows = list(candidates.values())
    # Bounded Jaccard candidates for human review: never auto-merge a changed
    # numeric value or silently decide which manufacturer/condition is correct.
    token_sets = [set(re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,}', r['claim'].lower())) for r in rows]
    for i, left in enumerate(rows):
        for j in range(i + 1, len(rows)):
            right = rows[j]
            a, b = token_sets[i], token_sets[j]
            similarity = len(a & b) / max(1, len(a | b))
            if similarity >= .78:
                numbers_changed = re.findall(r'[-+]?\d+(?:\.\d+)?', left['claim']) != re.findall(r'[-+]?\d+(?:\.\d+)?', right['claim'])
                units_changed = left['unit_tokens'] != right['unit_tokens']
                negation = r'\b(?:not|never|without|cannot)\b|不|无|未'
                polarity_changed = bool(re.search(negation, left['claim'], re.I)) != bool(re.search(negation, right['claim'], re.I))
                field = 'possible_conflict_ids' if numbers_changed or units_changed or polarity_changed else 'possible_duplicate_ids'
                left[field].append(right['candidate_id'])
                right[field].append(left['candidate_id'])
    for item in rows:
        item['related_candidate_ids'] = [r['candidate_id'] for r in rows if r['candidate_id'] != item['candidate_id'] and set(r['domain_tags']) & set(item['domain_tags'])][:8]
        errors = validate_candidate(item, sources, blocks)
        if errors:
            raise ValueError('merged_candidate_failed_validation:' + ','.join(errors))
        item['review_status'] = 'pending_review'
    return {'schema_version': SCHEMA_VERSION, 'candidates': rows, 'rejected': rejected,
            'summary': {'candidate_count': len(rows), 'human_reviewed': 0, 'published': 0,
                        'source_count': len({e['source_id'] for r in rows for e in r['evidence']}),
                        'by_type': dict(Counter(r['unit_type'] for r in rows)),
                        'by_domain': dict(Counter(t for r in rows for t in r['domain_tags'])),
                        'rejected_blocks': len(rejected), 'reviewed_KU_increment': 0,
                        'candidate_count_is_not_independent_knowledge_point_count': True}}
