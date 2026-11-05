"""Standard-library HTML extraction, with explicit logical-page provenance."""
from html.parser import HTMLParser
import re


class _DocumentHTML(HTMLParser):
    def __init__(self, scope):
        super().__init__(convert_charrefs=True)
        self.scope = scope
        self.scope_depth = 0
        self.ignored = []
        self.blocks = []
        self.text = []
        self.kind = 'paragraph'
        self.table = None
        self.row = None
        self.cell = None
        self.header = False

    def flush(self):
        text = re.sub(r'[ \t\r\n]+', ' ', ''.join(self.text)).strip()
        if text:
            self.blocks.append({'kind': self.kind, 'text': text})
        self.text = []

    def handle_starttag(self, tag, attrs):
        if self.scope and tag == self.scope:
            self.scope_depth += 1
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.append(tag)
            return
        if tag in {'script', 'style', 'nav', 'header', 'footer', 'head', 'noscript', 'svg'}:
            self.ignored.append(tag); return
        if self.scope and not self.scope_depth:
            return
        if tag == 'table':
            self.flush(); self.table = {'rows': [], 'header_rows': []}
        elif tag == 'tr' and self.table is not None:
            self.row = []; self.header = False
        elif tag in {'td', 'th'} and self.row is not None:
            self.cell = []
            self.header = self.header or tag == 'th'
        elif tag in {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'figcaption', 'blockquote'} and self.table is None:
            self.flush()
            self.kind = 'heading' if tag.startswith('h') and tag[1:].isdigit() else ('list_item' if tag == 'li' else 'paragraph')
        elif tag in {'br', 'hr'}:
            if self.cell is not None:
                self.cell.append('\n')
            else:
                self.text.append('\n')

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if self.scope and not self.scope_depth:
            return
        if tag in {'td', 'th'} and self.cell is not None:
            self.row.append(re.sub(r'\s+', ' ', ''.join(self.cell)).strip()); self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.header:
                self.table['header_rows'].append(len(self.table['rows']))
            self.table['rows'].append(self.row); self.row = None
        elif tag == 'table' and self.table is not None:
            self.table['header_status'] = 'explicit_html_th_not_professionally_reviewed' if self.table['header_rows'] else 'no_explicit_header'
            self.table['cell_bboxes'] = []
            self.blocks.append({'kind': 'table', 'text': '\n'.join('\t'.join(row) for row in self.table['rows']), 'table': self.table})
            self.table = None
        elif tag in {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'figcaption', 'blockquote'}:
            self.flush(); self.kind = 'paragraph'
        if self.scope and tag == self.scope:
            self.flush(); self.scope_depth -= 1

    def handle_data(self, data):
        if self.ignored or self.scope and not self.scope_depth:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.table is None:
            self.text.append(data)


def html_blocks(text):
    scope = 'main' if re.search(r'<main\b', text, re.I) else ('article' if re.search(r'<article\b', text, re.I) else None)
    parser = _DocumentHTML(scope)
    parser.feed(text); parser.close(); parser.flush()
    result = []
    for block in parser.blocks:
        if block['text'].strip():
            result.append({**block, 'page': 1, 'bbox': None,
                           'quality_flags': ['nonpaginated_source', 'bbox_unavailable', 'html_dom_machine_extracted']})
    return result, scope or 'document_without_navigation'
