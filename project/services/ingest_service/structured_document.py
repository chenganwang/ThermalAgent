"""Local, provenance-preserving PDF/text parsing; no database or model side effects.

Layout labels are heuristics, never professional review. Extracted spelling and
units are not repaired. The serialized blocks remain the evidence for chunks.
"""
from __future__ import annotations

from collections import Counter
from importlib.metadata import PackageNotFoundError, version
import hashlib
import math
from pathlib import Path
import re
import statistics
import time

PARSER_VERSION = 'structured-native-v1.4'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def _version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _bbox(items: list[dict]) -> list[float]:
    return [min(w['x0'] for w in items), min(w['top'] for w in items),
            max(w['x1'] for w in items), max(w['bottom'] for w in items)]


def _lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (round(w['top'] / 3), w['x0'])):
        if not lines or abs(word['top'] - statistics.median(w['top'] for w in lines[-1])) > 3:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda w: w['x0']) for line in lines]


def _numeric_table(words: list[dict]) -> dict | None:
    """Conservative borderless numeric table candidate; keep header ambiguity.

    Unlike pdfplumber text edges, columns come from repeated numeric row gaps.
    No missing cell values, powers or decimal points are repaired.
    """
    lines = _lines(words)
    caption = next((i for i, line in enumerate(lines) if re.match(r'^(?:Table|表)\s*\d', ' '.join(w['text'] for w in line), re.I)), None)
    if caption is None:
        return None
    candidates = []
    for i, line in enumerate(lines[caption + 1:], caption + 1):
        cells = []
        for word in line:
            if cells and word['x0'] - cells[-1][-1]['x1'] < 7:
                cells[-1].append(word)
            else:
                cells.append([word])
        strings = [' '.join(w['text'] for w in cell) for cell in cells]
        numeric = sum(bool(re.fullmatch(r'[+−–-]?[\d. ,Ee+−–-]+', value)) for value in strings)
        if len(cells) >= 4 and numeric / len(cells) >= .8:
            candidates.append((i, cells, strings))
    if len(candidates) < 6:
        return None
    ncols, count = Counter(len(cells) for _, cells, _ in candidates).most_common(1)[0]
    if count < 6 or count / len(candidates) < .6:
        return None
    # Reject drifting column positions rather than silently aligning values.
    complete = [(i, cells, strings) for i, cells, strings in candidates if len(cells) == ncols]
    centers = [statistics.median((cells[j][0]['x0'] + cells[j][-1]['x1']) / 2 for _, cells, _ in complete) for j in range(ncols)]
    if any(abs((cells[j][0]['x0'] + cells[j][-1]['x1']) / 2 - centers[j]) > 12 for _, cells, _ in complete for j in range(ncols)):
        return None
    first, last = candidates[0][0], candidates[-1][0]
    header_lines = lines[caption + 1:first]
    body_lines = lines[first:last + 1]
    all_words = [w for line in header_lines + body_lines for w in line]
    rows, cell_boxes = [], []
    # Preserve inconsistent rows too, with explicit review flags.
    mapping = {i: (cells, strings) for i, cells, strings in candidates}
    for i in range(first, last + 1):
        if i in mapping:
            cells, strings = mapping[i]
            rows.append(strings); cell_boxes.append([_bbox(c) for c in cells])
        else:
            rows.append([' '.join(w['text'] for w in lines[i])]); cell_boxes.append([_bbox(lines[i])])
    return {'bbox': _bbox(all_words), 'rows': rows, 'row_bboxes': [_bbox(line) for line in body_lines],
            'cell_bboxes': cell_boxes, 'header_rows': [],
            'header_text': '\n'.join(' '.join(w['text'] for w in line) for line in header_lines),
            'header_bbox': _bbox([w for line in header_lines for w in line]) if header_lines else None,
            'header_status': 'multirow_header_preserved_column_association_unverified',
            'extraction_method': 'numeric_alignment_candidate',
            'column_count_candidate': ncols,
            'irregular_row_count': sum(len(row) != ncols for row in rows)}


def _native_blocks(page, page_number: int, *, detect_tables: bool) -> tuple[list[dict], list[str]]:
    flags: list[str] = []
    tables = []
    if detect_tables:
        try:
            for table in page.find_tables():
                rows = table.extract()
                if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
                    continue
                tables.append({'bbox': list(table.bbox), 'rows': rows,
                               'row_bboxes': [list(r.bbox) for r in table.rows],
                               'cell_bboxes': [[list(c) if c else None for c in r.cells] for r in table.rows]})
        except Exception as exc:
            flags.append('table_detection_failed:' + type(exc).__name__)
    words = page.extract_words(x_tolerance=2, y_tolerance=3, extra_attrs=['size'])
    if detect_tables and not tables:
        numeric = _numeric_table(words)
        if numeric:
            tables.append(numeric)
            flags.append('borderless_numeric_table_machine_candidate')
    outside = [w for w in words if not any(t['bbox'][0] <= (w['x0'] + w['x1']) / 2 <= t['bbox'][2]
               and t['bbox'][1] <= (w['top'] + w['bottom']) / 2 <= t['bbox'][3] for t in tables)]
    # A conservative two-column detector: require both populated sides and a
    # repeated wide center gutter. Spanning headings remain separate anchors.
    all_lines = _lines(outside)
    middle = page.width / 2
    gutter_lines = sum(any(a['x1'] < middle < b['x0'] and b['x0'] - a['x1'] > 24
                          for a, b in zip(line, line[1:])) for line in all_lines)
    occupied_center_lines = sum(any(w['x0'] < middle + 6 and w['x1'] > middle - 6 for w in line) for line in all_lines)
    # Staggered baselines yield many one-column lines; dividing gutter matches
    # by all lines misses real two-column documents. Test the persistent empty
    # center band instead, while requiring repeated matches on both sides.
    two_column = gutter_lines >= 5 and occupied_center_lines <= max(2, len(all_lines) * .2)
    if two_column:
        flags.append('two_column_reading_order_heuristic')
        spanning = [line for line in all_lines if any(w['x0'] < middle < w['x1'] for w in line)]
        # Process vertical bands between full-width anchors, then left/right.
        anchors = sorted(spanning, key=lambda line: _bbox(line)[1])
        sequence = []
        remaining = [w for line in all_lines if line not in spanning for w in line]
        for anchor in anchors + [None]:
            top = _bbox(anchor)[1] if anchor else float('inf')
            band = [w for w in remaining if w['top'] < top]
            remaining = [w for w in remaining if w['top'] >= top]
            sequence.extend(_lines([w for w in band if (w['x0'] + w['x1']) / 2 < middle]))
            sequence.extend(_lines([w for w in band if (w['x0'] + w['x1']) / 2 >= middle]))
            if anchor:
                sequence.append(anchor)
        all_lines = sequence
    sizes = [float(w['size']) for w in words if float(w['size']) > 0]
    typical = statistics.median(sizes) if sizes else 10
    blocks = []
    for line in all_lines:
        text = ' '.join(w['text'] for w in line)
        size = statistics.median(float(w['size']) for w in line)
        kind = 'paragraph'
        if re.match(r'^(?:Table|表)\s*\d', text, re.I):
            kind = 'table_caption'
        elif re.match(r'^(?:Fig(?:ure)?\.?|图)\s*\d', text, re.I):
            kind = 'figure_caption'
        elif ('=' in text or '∝' in text or '≈' in text) and len(text) < 300:
            kind = 'formula'
        elif len(text) < 180 and (size >= typical * 1.25 or re.match(r'^\d+(?:\.\d+)*\s+[A-Za-z\u4e00-\u9fff]', text)):
            kind = 'heading'
        elif re.match(r'^(?:[•●▪]|[-–]\s|\(?\d+[.)]\s)', text):
            kind = 'list_item'
        box = _bbox(line)
        if blocks and kind == 'formula' and blocks[-1]['kind'] == 'paragraph':
            prev = blocks[-1]
            if (re.match(r'^(?:rather\b|then\b|provided\b|则|即)', text, re.I)
                    and not re.search(r'[.!?。！？:]$', prev['text'])
                    and -1 <= box[1] - prev['bbox'][3] <= typical * .7
                    and abs(box[0] - prev['bbox'][0]) < 12):
                prev['text'] += '\n' + text
                prev['kind'] = 'formula'
                prev['bbox'] = [min(prev['bbox'][0], box[0]), prev['bbox'][1], max(prev['bbox'][2], box[2]), box[3]]
                prev['quality_flags'].append('inline_formula_with_source_sentence')
                continue
        if blocks and kind == 'paragraph' and blocks[-1]['kind'] == kind:
            prev = blocks[-1]
            gap = box[1] - prev['bbox'][3]
            if -1 <= gap <= typical * .7 and abs(box[0] - prev['bbox'][0]) < 24:
                prev['text'] += '\n' + text
                prev['bbox'] = [min(prev['bbox'][0], box[0]), prev['bbox'][1], max(prev['bbox'][2], box[2]), box[3]]
                continue
        blocks.append({'page': page_number, 'bbox': box, 'kind': kind, 'text': text,
                       'quality_flags': ['layout_label_machine_inferred']})
    for table in tables:
        text = '\n'.join(filter(None, [table.get('header_text'), '\n'.join('\t'.join(cell or '' for cell in row) for row in table['rows'])]))
        blocks.append({'page': page_number, 'bbox': table['bbox'], 'kind': 'table', 'text': text,
                       'table': {'header_rows': [0], 'header_status': 'first_row_candidate_not_reviewed', **table},
                       'quality_flags': ['table_cells_machine_extracted', 'table_header_unverified']})
    if tables and not two_column:
        blocks.sort(key=lambda b: (b['bbox'][1], b['bbox'][0]))
    elif tables and two_column:
        flags.append('table_column_order_requires_review')
    return blocks, flags


def parse_document(path: str | Path, source_id: str, source_metadata: dict | None = None,
                   options: dict | None = None) -> dict:
    """Read local source. OCR is opt-in and reuses existing versioned OCR cache."""
    started = time.perf_counter()
    path = Path(path).resolve()
    options = dict(options or {})
    metadata = dict(source_metadata or {})
    digest = sha256_file(path)
    if metadata.get('sha256') and metadata['sha256'] != digest:
        raise ValueError('source SHA256 does not match supplied manifest')
    blocks, pages, flags = [], [], []
    if path.suffix.lower() == '.pdf':
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            selected = options.get('pages') or list(range(1, len(pdf.pages) + 1))
            if any(isinstance(p, bool) or not isinstance(p, int) or p < 1 or p > len(pdf.pages) for p in selected):
                raise ValueError('pages must be valid one-based PDF page numbers')
            if len(set(selected)) != len(selected):
                raise ValueError('duplicate page selection')
            for number in sorted(selected):
                page = pdf.pages[number - 1]
                items, page_flags = _native_blocks(page, number, detect_tables=options.get('detect_tables', True))
                method = 'native_pdfplumber'
                if sum(len(b['text']) for b in items) < 40:
                    page_flags.append('text_layer_sparse_or_scanned')
                    if options.get('ocr_config') is not None:
                        from .ocr_pdf import _ensure_cache_dir, _ocr_single_page
                        cfg = options['ocr_config']
                        text = _ocr_single_page(path, cfg, page=number, cache_dir=_ensure_cache_dir(cfg, digest))
                        if text.strip():
                            items = [{'page': number, 'bbox': None, 'kind': 'paragraph', 'text': text,
                                      'quality_flags': ['ocr_unverified', 'bbox_unavailable', 'formula_units_require_review']}]
                            method = 'ocr_tesseract'
                    else:
                        page_flags.append('ocr_not_requested')
                pages.append({'page': number, 'width': page.width, 'height': page.height,
                              'extraction_method': method, 'quality_flags': page_flags,
                              'image_count': len(page.images)})
                blocks.extend(items)
                page.close()
            total_pages = len(pdf.pages)
    else:
        if path.suffix.lower() not in {'.txt', '.md', '.html', '.htm'}:
            raise ValueError('only local PDF, UTF-8 text, Markdown or HTML supported')
        text = path.read_text(encoding='utf-8')
        if path.suffix.lower() in {'.html', '.htm'}:
            from .structured_html import html_blocks
            blocks, scope = html_blocks(text)
            flags.append('html_dom_scope:' + scope)
        else:
            blocks = [{'page': 1, 'bbox': None, 'kind': 'paragraph', 'text': part,
                       'quality_flags': ['nonpaginated_source', 'bbox_unavailable']}
                      for part in re.split(r'\n\s*\n', text) if part.strip()]
        pages = [{'page': 1, 'width': None, 'height': None, 'extraction_method': 'utf8_text', 'quality_flags': ['logical_page_not_pdf_page']}]
        total_pages = 1
    # Repeated margin blocks remain in the artifact; exclude only their
    # retrieval view, never remove source text from the evidence artifact.
    page_map = {p['page']: p for p in pages}
    candidates = []
    for block in blocks:
        box, height = block['bbox'], page_map[block['page']]['height']
        if box and height and (box[3] < height * .08 or box[1] > height * .92):
            candidates.append((block, re.sub(r'\d+', '#', re.sub(r'\s+', ' ', block['text']).strip())))
    freq = Counter(key for _, key in candidates)
    for block, key in candidates:
        if freq[key] >= max(3, math.ceil(len(pages) / 2)):
            block['quality_flags'].append('repeated_margin_candidate')
            block['exclude_from_retrieval'] = True
    section = []
    for order, block in enumerate(blocks):
        block.update(block_id=f'{digest[:16]}:p{block["page"]}:b{order}', order=order, relations=[])
        if block['kind'] == 'heading':
            match = re.match(r'^(\d+(?:\.\d+)*)\s', block['text'])
            level = min(6, match.group(1).count('.') + 1) if match else 1
            section = section[:level - 1] + [block['text']]
        block['section_path'] = list(section)
        if '\ufffd' in block['text'] or '\x00' in block['text']:
            block['quality_flags'].append('replacement_or_control_character')
        if block['kind'] == 'formula':
            block['quality_flags'].append('formula_symbols_unverified')
        if len(block['text'].strip()) <= 5 and not any(ch.isalnum() for ch in block['text']):
            block['quality_flags'].append('isolated_symbol_needs_context')
            block['exclude_from_retrieval'] = True
        if re.search(r'\d\s*(?:[mkM]?W|[mkM]?Pa|[muμ]?m|K|°C|kg|L/min)\b', block['text']):
            block['quality_flags'].append('engineering_units_require_review')
    for index, block in enumerate(blocks):
        for nearby in blocks[index + 1:index + 4]:
            if nearby['page'] != block['page'] or nearby['kind'] == 'heading':
                break
            if block['kind'] == 'formula' and re.match(r'^\s*(?:where\b|wherein\b|式中|其中|式内)', nearby['text'], re.I):
                block['relations'].append({'type': 'variable_definition_candidate', 'target_block_id': nearby['block_id']})
            if block['kind'] == 'formula' and re.search(r'\b(?:assum|steady|valid|provided|condition)\w*\b|稳态|适用|假设|条件', nearby['text'], re.I):
                block['relations'].append({'type': 'applicability_candidate', 'target_block_id': nearby['block_id']})
            if block['kind'] in {'table_caption', 'figure_caption'} and nearby['kind'] == ('table' if block['kind'] == 'table_caption' else 'paragraph'):
                block['relations'].append({'type': 'caption_association_candidate', 'target_block_id': nearby['block_id']})
                break
    safe_options = {k: v for k, v in options.items() if k != 'ocr_config'}
    return {'schema_version': 'structured-document-v1',
            'document': {'source_id': source_id, 'sha256': digest, 'path': str(path), 'mime': metadata.get('mime'),
                         'title': metadata.get('title', path.stem), 'source_document_version': metadata.get('version') or digest,
                         'metadata': metadata, 'total_pages': total_pages},
            'parser': {'name': PARSER_VERSION, 'version': PARSER_VERSION, 'options': safe_options,
                       'dependency_versions': {n: _version(n) for n in ('pdfplumber', 'pdfminer.six', 'pypdf')},
                       'ocr_requested': options.get('ocr_config') is not None},
            'pages': pages, 'blocks': blocks, 'quality_flags': flags,
            'review_status': 'machine_draft', 'human_reviewed': False,
            'metrics': {'parse_seconds': time.perf_counter() - started, 'pages_parsed': len(pages),
                        'blocks': len(blocks), 'characters': sum(len(b['text']) for b in blocks)}}
