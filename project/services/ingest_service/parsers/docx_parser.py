from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
import hashlib
import re

from ..chunking.types import Block


def _normalize_text(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _is_numeric_like(x: str) -> bool:
    x = (x or "").strip()
    if not x:
        return False
    return bool(re.fullmatch(r"[\d\.\-–—±+eE%/()×·℃KPaMPaWmkgNsμuΩohm\s]+", x))


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    s = style_name.strip().lower()
    m = re.search(r"heading\s*(\d+)", s)
    if m:
        return int(m.group(1))
    m = re.search(r"标题\s*(\d+)", s)
    if m:
        return int(m.group(1))
    return None


def _is_caption_style(style_name: str | None) -> bool:
    if not style_name:
        return False
    s = style_name.strip().lower()
    return s == "caption" or "题注" in s


def infer_table_headers(rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    if not rows:
        return [], []
    first = rows[0]

    def is_texty(cell: str) -> bool:
        cell = (cell or "").strip()
        if not cell:
            return False
        if _is_numeric_like(cell):
            return False
        return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", cell))

    texty = sum(1 for c in first if is_texty(c))
    numeric = sum(1 for c in first if _is_numeric_like(c))
    nonempty = sum(1 for c in first if (c or "").strip())
    if nonempty > 0 and texty >= max(1, int(nonempty * 0.5)) and numeric <= max(0, int(nonempty * 0.2)):
        return [c.strip() for c in first], rows[1:]
    return [], rows


def parse_docx_to_blocks(docx_path: Path) -> List[Block]:
    """Parse DOCX into a linear block stream with heading-aware metadata.

    page numbers are not reliable in python-docx, so default to page=1.
    Important structure is moved into block.meta:
      - heading_level
      - section_path
      - style_name
      - caption / prev_text for figures and tables
    """
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(docx_path))
    blocks: List[Block] = []
    page = 1
    order = 0
    last_text_para = ""
    prev_para_for_table = ""
    last_heading_text = ""
    last_caption_text = ""
    section_stack: list[str] = []

    def iter_block_items(parent):
        for child in parent.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def extract_images_from_paragraph(p: Paragraph) -> List[Tuple[str, str]]:
        xml = p._p.xml
        rel_ids = re.findall(r'r:embed="([^"]+)"', xml)
        out: List[Tuple[str, str]] = []
        for rid in rel_ids:
            try:
                part = doc.part.related_parts[rid]
                img_id = _sha256_bytes(part.blob)[:16]
                out.append((img_id, rid))
            except Exception:
                continue
        return out

    def update_section_stack(level: int, text: str) -> str:
        nonlocal section_stack
        while len(section_stack) >= level:
            section_stack.pop()
        section_stack.append(text)
        return " > ".join(section_stack)

    table_counter = 0

    for item in iter_block_items(doc):
        if isinstance(item, Paragraph):
            t = _normalize_text(item.text or "")
            style_name = getattr(getattr(item, "style", None), "name", None)
            heading_level = _heading_level(style_name)
            is_caption = _is_caption_style(style_name)
            imgs = extract_images_from_paragraph(item)

            section_path = None
            if heading_level and t:
                section_path = update_section_stack(heading_level, t)
                last_heading_text = t
            elif section_stack:
                section_path = " > ".join(section_stack)

            if t:
                meta = {
                    "style_name": style_name,
                    "section_path": section_path,
                }
                if heading_level:
                    meta["heading_level"] = heading_level
                if is_caption:
                    meta["is_caption"] = True
                    last_caption_text = t
                blocks.append(Block(page=page, type="text", order=order, text=t, meta=meta))
                order += 1
                last_text_para = t
                prev_para_for_table = t

            if imgs:
                caption = last_caption_text.strip() if last_caption_text else (t.strip() if is_caption else "")
                anchor_before = last_text_para.strip()
                for (img_id, rid) in imgs:
                    body = f"[图] {caption} (docx)" if caption else "[图] (docx)"
                    if anchor_before:
                        body += f"\n[图前文本锚点] {anchor_before[:200].replace(chr(10), ' ')}"
                    blocks.append(
                        Block(
                            page=page,
                            type="figure",
                            order=order,
                            text=body,
                            meta={
                                "image_id": img_id,
                                "rel_id": rid,
                                "caption": caption or None,
                                "prev_text": anchor_before,
                                "section_path": section_path,
                                "prev_heading": last_heading_text or None,
                            },
                        )
                    )
                    order += 1

        elif isinstance(item, Table):
            raw_rows: List[List[str]] = []
            for row in item.rows:
                raw_rows.append([_normalize_text(cell.text) for cell in row.cells])
            rows = [r for r in raw_rows if any((c or "").strip() for c in r)]
            if not rows:
                continue
            headers, data_rows = infer_table_headers(rows)
            table_id = f"docx_table_{table_counter}"
            table_counter += 1
            section_path = " > ".join(section_stack) if section_stack else None
            caption = last_caption_text or (prev_para_for_table if prev_para_for_table and re.match(r"^(表|table)\s*\d", prev_para_for_table, re.I) else "")
            blocks.append(
                Block(
                    page=page,
                    type="table",
                    order=order,
                    text="",
                    meta={
                        "headers": headers,
                        "rows": data_rows,
                        "prev_text": prev_para_for_table,
                        "table_id": table_id,
                        "caption": caption or None,
                        "section_path": section_path,
                        "prev_heading": last_heading_text or None,
                    },
                )
            )
            order += 1

    return sorted(blocks, key=lambda b: (b.page, b.order))
