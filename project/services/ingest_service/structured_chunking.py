"""Comparable chunk policies over one immutable structured-document artifact."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import time

CHUNK_VERSION = 'structured-chunks-v1'
STRATEGIES = ('fixed', 'structure', 'semantic', 'semantic_tfidf', 'parent_child', 'engineering')


def _identity(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _span(block: dict, start: int = 0, end: int | None = None) -> dict:
    return {'block_id': block['block_id'], 'start': start, 'end': len(block['text']) if end is None else end,
            'page': block['page'], 'bbox': block.get('bbox')}


def _make(document: dict, spans: list[dict], strategy: str, options: dict, *, parent_id=None,
          context_spans: list[dict] | None = None) -> dict:
    block_map = {b['block_id']: b for b in document['blocks']}
    text = '\n\n'.join(block_map[s['block_id']]['text'][s['start']:s['end']] for s in spans)
    context_spans = context_spans or []
    record = {'text': text, 'source_id': document['document']['source_id'],
              'document_sha256': document['document']['sha256'],
              'source_document_version': document['document']['source_document_version'],
              'page_start': min(s['page'] for s in spans), 'page_end': max(s['page'] for s in spans),
              'block_ids': list(dict.fromkeys(s['block_id'] for s in spans)), 'source_spans': spans,
              'section_path': block_map[spans[0]['block_id']].get('section_path', []), 'parent_id': parent_id,
              'strategy': strategy, 'strategy_version': CHUNK_VERSION,
              'review_status': 'machine_draft', 'human_reviewed': False,
              'context': {'kind': 'extracted_source_only', 'source_spans': context_spans,
                          'text': '\n\n'.join(block_map[s['block_id']]['text'][s['start']:s['end']] for s in context_spans)},
              'quality_flags': sorted({f for s in spans for f in block_map[s['block_id']].get('quality_flags', [])}),
              'table_context': []}
    for ident in record['block_ids']:
        block = block_map[ident]
        if block.get('table'):
            table = block['table']
            owned_spans = [s for s in spans if s['block_id'] == ident]
            offset = len(table.get('header_text') or '') + (1 if table.get('header_text') else 0)
            selected_rows = []
            for row_index, row in enumerate(table['rows']):
                end = offset + len('\t'.join(cell or '' for cell in row))
                if any(s['start'] < end and s['end'] > offset for s in owned_spans):
                    selected_rows.append(row_index)
                offset = end + 1
            record['table_context'].append({'block_id': ident, 'header_status': table['header_status'],
                'header_rows': [table['rows'][r] for r in table['header_rows']],
                'header_text': table.get('header_text'), 'header_bbox': table.get('header_bbox'),
                'rows': [table['rows'][i] for i in selected_rows], 'row_indices': selected_rows,
                'cell_bboxes': [table.get('cell_bboxes', [])[i] for i in selected_rows if i < len(table.get('cell_bboxes', []))],
                'kind': 'extracted_table_metadata_not_additional_raw_text'})
    record['chunk_id'] = _identity([record['source_id'], record['document_sha256'], strategy, CHUNK_VERSION,
                                    options, spans, parent_id, context_spans])[:32]
    return record


def _units(blocks: list[dict], max_chars: int, *, engineering: bool) -> list[list[dict]]:
    """Hard split by source offsets. Tables split only on row boundaries where possible."""
    units = []
    for block in blocks:
        text = block['text']
        if len(text) <= max_chars:
            units.append([_span(block)])
            continue
        start = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            if end < len(text):
                if block['kind'] == 'table' or engineering:
                    split = text.rfind('\n', start + max_chars // 2, end)
                    if split > start:
                        end = split + 1
                else:
                    split = text.rfind(' ', start + max_chars // 2, end)
                    if split > start:
                        end = split + 1
            units.append([_span(block, start, end)])
            start = end
    return units


def _vector_breaks(blocks: list[dict], vectors: dict, percentile: float) -> set[str]:
    if any(b['block_id'] not in vectors for b in blocks):
        raise ValueError('semantic vectors must cover every included block')
    size = None
    normalized = []
    for block in blocks:
        raw = vectors[block['block_id']]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError('semantic vectors must be nonempty arrays')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in raw):
            raise ValueError('semantic vectors must contain finite numbers')
        if size is None:
            size = len(raw)
        if len(raw) != size:
            raise ValueError('semantic vector dimensions differ')
        norm = math.sqrt(sum(x*x for x in raw))
        if not norm:
            raise ValueError('semantic zero vector cannot define cosine similarity')
        normalized.append([x / norm for x in raw])
    distances = [max(0., 1. - sum(x*y for x, y in zip(a, b))) for a, b in zip(normalized, normalized[1:])]
    if not distances:
        return set()
    threshold = sorted(distances)[min(len(distances) - 1, int((len(distances) - 1) * percentile / 100))]
    return {blocks[i + 1]['block_id'] for i, distance in enumerate(distances) if distance > 0 and distance >= threshold}


def chunk_document(document: dict, strategy: str, options: dict | None = None, *,
                   block_embeddings: dict | None = None, embedding_provider=None) -> dict:
    """Dense semantic vectors are supplied by the caller; this module loads no model."""
    started = time.perf_counter()
    if strategy not in STRATEGIES:
        raise ValueError('unknown chunk strategy')
    options = {'max_chars': 1000, 'parent_max_chars': 3000, 'semantic_percentile': 75, **(options or {})}
    max_chars = options['max_chars']
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 64:
        raise ValueError('max_chars must be integer >=64')
    if options['parent_max_chars'] < max_chars or not 0 <= options['semantic_percentile'] <= 100:
        raise ValueError('invalid parent budget or semantic percentile')
    blocks = [b for b in document['blocks'] if b['text'].strip() and not b.get('exclude_from_retrieval')]
    index = {b['block_id']: b for b in blocks}
    breaks, mode, unavailable = set(), None, None
    if strategy == 'semantic':
        if embedding_provider is not None:
            if block_embeddings is not None:
                raise ValueError('choose either precomputed embeddings or provider')
            values = embedding_provider([b['text'] for b in blocks])
            if len(values) != len(blocks):
                raise ValueError('embedding provider count mismatch')
            block_embeddings = {b['block_id']: [float(x) for x in row] for b, row in zip(blocks, values)}
        if block_embeddings is None:
            unavailable = 'precomputed block embeddings/provider required; no silent lexical fallback'
        else:
            breaks = _vector_breaks(blocks, block_embeddings, options['semantic_percentile'])
            options['embedding_digest'] = _identity(block_embeddings)
            mode = 'supplied_dense_vectors'
    elif strategy == 'semantic_tfidf':
        # Explicit lexical proxy, separate from the dense semantic strategy.
        from sklearn.feature_extraction.text import TfidfVectorizer
        if len(blocks) >= 2:
            matrix = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=20000).fit_transform(b['text'] for b in blocks)
            distances = [1. - float(matrix[i].multiply(matrix[i + 1]).sum()) for i in range(len(blocks) - 1)]
            threshold = sorted(distances)[int((len(distances) - 1) * options['semantic_percentile'] / 100)]
            breaks = {blocks[i + 1]['block_id'] for i, d in enumerate(distances) if d > 0 and d >= threshold}
        mode = 'character_tfidf_lexical_proxy_not_dense_semantics'
    if unavailable:
        return {'strategy': strategy, 'strategy_version': CHUNK_VERSION, 'status': 'unavailable',
                'reason': unavailable, 'chunks': [], 'parents': [], 'options': options,
                'metrics': {'chunk_count': 0, 'build_seconds': time.perf_counter() - started}}
    parents, chunks = [], []
    if strategy == 'fixed':
        # Same source blocks and budget, no overlap: only splitting policy differs.
        current, used = [], 0
        for block in blocks:
            start = 0
            while start < len(block['text']):
                room = max_chars - used - (2 if current else 0)
                if room <= 0:
                    chunks.append(_make(document, current, strategy, options)); current, used = [], 0
                    continue
                end = min(len(block['text']), start + room)
                current.append(_span(block, start, end))
                used += end - start + (2 if len(current) > 1 else 0)
                start = end
        if current:
            chunks.append(_make(document, current, strategy, options))
    else:
        budget = options['parent_max_chars'] if strategy == 'parent_child' else max_chars
        units = _units(blocks, budget, engineering=strategy == 'engineering')
        current, used, section = [], 0, None
        groups = []
        for unit in units:
            first = index[unit[0]['block_id']]
            size = sum(s['end'] - s['start'] for s in unit)
            new_section = first.get('section_path', [])
            should_break = (current and (used + size + 2 > budget or new_section != section or first['kind'] == 'heading'
                            or (first['block_id'] in breaks and used >= max_chars // 3)))
            if should_break:
                groups.append(current); current, used = [], 0
            current.extend(unit); used += size + (2 if len(current) > 1 else 0); section = new_section
        if current:
            groups.append(current)
        for group in groups:
            if strategy == 'parent_child':
                parent = _make(document, group, strategy + '_parent', options)
                parents.append(parent)
                children = []
                used = 0
                for span in group:
                    block = index[span['block_id']]
                    offset = span['start']
                    while offset < span['end']:
                        room = max_chars - used - (2 if children else 0)
                        if room <= 0:
                            chunks.append(_make(document, children, strategy, options, parent_id=parent['chunk_id'])); children, used = [], 0
                            continue
                        end = min(span['end'], offset + room)
                        children.append(_span(block, offset, end)); used += end - offset + (2 if len(children) > 1 else 0); offset = end
                if children:
                    chunks.append(_make(document, children, strategy, options, parent_id=parent['chunk_id']))
            else:
                context = []
                if strategy == 'engineering':
                    owned = {s['block_id'] for s in group}
                    # Retain linked source evidence separately instead of
                    # making copied context look like contiguous original text.
                    for block in blocks:
                        for link in block.get('relations', []):
                            pair = {block['block_id'], link['target_block_id']}
                            if pair & owned:
                                for ident in sorted(pair - owned):
                                    if ident in index:
                                        candidate = _span(index[ident])
                                        if candidate not in context and sum(s['end'] - s['start'] for s in context) + candidate['end'] <= max_chars:
                                            context.append(candidate)
                chunks.append(_make(document, group, strategy, options, context_spans=context))
    metrics = evaluate_chunks(document, chunks, parents)
    metrics['build_seconds'] = time.perf_counter() - started
    return {'strategy': strategy, 'strategy_version': CHUNK_VERSION, 'status': 'ok', 'semantic_mode': mode,
            'options': options, 'chunks': chunks, 'parents': parents, 'metrics': metrics}


def evaluate_chunks(document: dict, chunks: list[dict], parents: list[dict] | None = None) -> dict:
    blocks = {b['block_id']: b for b in document['blocks'] if b['text'].strip() and not b.get('exclude_from_retrieval')}
    spans_by_block = {key: [] for key in blocks}
    valid = 0
    for chunk in chunks:
        reconstructed = []
        spans_ok = True
        for s in chunk['source_spans']:
            b = blocks.get(s['block_id'])
            if not b or not 0 <= s['start'] < s['end'] <= len(b['text']) or s['page'] != b['page']:
                spans_ok = False; continue
            reconstructed.append(b['text'][s['start']:s['end']])
            spans_by_block[s['block_id']].append((s['start'], s['end']))
        valid += int(spans_ok and '\n\n'.join(reconstructed) == chunk['text'])
    parent_map = {p['chunk_id']: p for p in parents or []}
    def fully_present(chunk, key):
        spans = chunk['source_spans'] + chunk['context']['source_spans']
        if chunk.get('parent_id') in parent_map:
            spans += parent_map[chunk['parent_id']]['source_spans']
        return any(s['block_id'] == key and s['start'] == 0 and s['end'] == len(blocks[key]['text']) for s in spans)
    tables = [key for key, b in blocks.items() if b['kind'] == 'table']
    pairs = [(key, r['target_block_id']) for key, b in blocks.items() for r in b.get('relations', [])
             if r['type'] == 'variable_definition_candidate' and r['target_block_id'] in blocks]
    complete = sum(any(fully_present(c, key) for c in chunks) for key in tables)
    separated = sum(not any(fully_present(c, a) and fully_present(c, b) for c in chunks) for a, b in pairs)
    lengths = sorted(len(c['text']) for c in chunks)
    def ratio(n, d):
        return n / d if d else None
    return {'chunk_count': len(chunks), 'parent_count': len(parents or []),
            'mean_chars': statistics.mean(lengths) if lengths else 0,
            'p50_chars': lengths[int((len(lengths) - 1) * .5)] if lengths else 0,
            'p95_chars': lengths[int((len(lengths) - 1) * .95)] if lengths else 0,
            'max_chars': max(lengths, default=0),
            'structure_boundary_split_proxy': {'numerator': sum(len(set(v)) > 1 for v in spans_by_block.values()), 'denominator': len(blocks), 'value': ratio(sum(len(set(v)) > 1 for v in spans_by_block.values()), len(blocks))},
            'formula_variable_separation_proxy': {'numerator': separated, 'denominator': len(pairs), 'value': ratio(separated, len(pairs))},
            'table_whole_evidence_proxy': {'numerator': complete, 'denominator': len(tables), 'value': ratio(complete, len(tables))},
            'source_span_traceability': {'numerator': valid, 'denominator': len(chunks), 'value': ratio(valid, len(chunks))},
            'exact_duplicate_rate': ratio(len(chunks) - len({_identity(c['text']) for c in chunks}), len(chunks)),
            'recall_at_k': {'status': 'unavailable', 'reason': 'requires independent relevance labels and actual retrieval'},
            'mrr': {'status': 'unavailable', 'reason': 'requires independent relevance labels and actual retrieval'},
            'metric_scope': 'machine structure proxies; parent/source context counts as available evidence; not expert gold'}
