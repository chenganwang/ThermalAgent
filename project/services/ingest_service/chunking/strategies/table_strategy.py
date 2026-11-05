from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .base import ChunkStrategy
from ..types import Block, Chunk, ChunkContext
from .text_strategy import approx_tokens
from ..normalize import normalize_cell_text, compact_values

_CAPTION_PAT = re.compile(r"^\s*(表|Table)\s*[\dIVXivx]+([\-–\.]\d+)*\b")
_HEADER_ALIASES = {
    "温度": ["温度", "t", "temp", "temperature"],
    "压力": ["压力", "p", "press", "pressure"],
    "热导率": ["热导率", "导热系数", "k", "conductivity"],
    "密度": ["密度", "rho", "ρ", "density"],
    "比热": ["比热", "cp", "c_p", "specific heat"],
}


def _budget_len(text: str, ctx: ChunkContext) -> int:
    return approx_tokens(text) if ctx.use_token_budget else len(text)


def _caption_from_prev(prev: str, *, max_len: int = 220) -> str:
    t = (prev or "").strip()
    if not t:
        return ""
    t = t[-max_len:]
    lines = [ln.strip() for ln in re.split(r"\n+", t) if ln.strip()]
    for ln in reversed(lines[-6:]):
        if _CAPTION_PAT.search(ln):
            return ln
        if ln.startswith("表") and re.search(r"\d", ln[:14]):
            return ln
    return ""


def _table_anchor(prev: str, caption: str, *, max_len: int = 140) -> str:
    t = normalize_cell_text((prev or "").strip())
    if not t:
        return ""
    lines = [ln.strip() for ln in re.split(r"\n+", t) if ln.strip()]
    cand = ""
    for ln in reversed(lines[-5:]):
        if caption and caption in ln:
            continue
        if len(ln) >= 10:
            cand = ln
            break
    cand = cand[-max_len:].strip()
    if not cand:
        return ""
    return f"[表前说明] {cand}"


def _canonical_header(header: str) -> str:
    h = normalize_cell_text(header)
    low = h.lower()
    for canon, aliases in _HEADER_ALIASES.items():
        if any(a.lower() == low for a in aliases):
            return canon
    return h


def _header_text(caption: str, headers: List[str], page: int, *, col_slice: Optional[Tuple[int, int]] = None) -> str:
    cap = caption.strip()
    sl = f"列[{col_slice[0]}:{col_slice[1]}]" if col_slice is not None else ""
    t1 = f"[表] {cap} (p.{page})" if cap else f"[表] (p.{page})"
    if sl:
        t1 = f"{t1} {sl}"
    t2 = "列: " + ", ".join(h.strip() for h in headers if h.strip()) if headers else "列: (无明显表头)"
    return f"{t1}\n{t2}"


def _row_kv(headers: List[str], row: List[str]) -> str:
    r = [normalize_cell_text(str(x)) for x in row]
    hh = [_canonical_header(h) for h in headers]
    if hh and len(hh) == len(r):
        return "行: " + "; ".join(f"{hh[i]}={r[i]}" for i in range(len(hh)))
    return "行: " + " | ".join(r)


def _row_values_compact(row: List[str]) -> str:
    val = compact_values([str(x) for x in row])
    return f"值: {val}" if val else ""


def _same_table(a: Chunk, b: Chunk) -> bool:
    ma, mb = a.meta or {}, b.meta or {}
    if ma.get('table_id') and ma.get('table_id') == mb.get('table_id'):
        return True
    if ma.get('caption') and ma.get('caption') == mb.get('caption'):
        return True
    return False


def _merge_small_tables(chunks: List[Chunk], min_chars: int, hard_max: int) -> List[Chunk]:
    if not chunks:
        return chunks
    out: List[Chunk] = []
    for c in chunks:
        if out and c.type == 'table' and out[-1].type == 'table':
            p = out[-1]
            same_id = _same_table(p, c)
            if same_id and (len(p.text) < min_chars or len(c.text) < min_chars) and len(p.text) + len(c.text) + 2 <= int(hard_max * 1.15):
                p.text = (p.text.rstrip() + "\n" + c.text.lstrip()).strip()
                p.page_end = max(p.page_end, c.page_end)
                p.meta['row_end'] = c.meta.get('row_end', p.meta.get('row_end'))
                continue
        out.append(c)
    return out


class TableStrategy(ChunkStrategy):
    def supports(self, block: Block) -> bool:
        return block.type == "table"

    def chunk(self, block: Block, ctx: ChunkContext) -> List[Chunk]:
        headers: List[str] = [_canonical_header(h) for h in (block.meta.get("headers", []) or [])]
        rows: List[List[str]] = [
            [normalize_cell_text(str(cell)) for cell in row]
            for row in (block.meta.get("rows", []) or [])
        ]
        if not rows:
            t = normalize_cell_text((block.text or "").strip())
            return [Chunk(block.page, block.page, "table", t, dict(block.meta))] if t else []

        caption = normalize_cell_text((block.meta.get("caption") or "").strip()) or _caption_from_prev(block.meta.get("prev_text", ""))
        anchor = _table_anchor(block.meta.get("prev_text", ""), caption)
        table_id = block.meta.get("table_id")
        row_count = len(rows)
        col_count = max((len(r) for r in rows), default=len(headers))
        out: List[Chunk] = []

        col_per = max(1, int(ctx.table_cols_per_slice))
        if headers and len(headers) > col_per:
            slices = [(i, min(i + col_per, len(headers))) for i in range(0, len(headers), col_per)]
        else:
            slices = [(0, len(headers) if headers else col_count)]

        for slice_idx, (cs, ce) in enumerate(slices):
            h2 = headers[cs:ce] if headers else headers
            rows2 = [r[cs:ce] if isinstance(r, list) else [str(r)] for r in rows]
            base = _header_text(caption, h2, block.page, col_slice=(cs, ce) if len(slices) > 1 else None)
            if anchor:
                base = base + "\n" + anchor
            base_len = _budget_len(base, ctx) + 1
            target = int(ctx.table_target_chars)
            hard_max = int(ctx.table_hard_max_chars)
            min_chars = int(getattr(ctx, 'table_min_emit_chars', getattr(ctx, 'table_min_chars', 320)))
            min_rows = 4 if len(rows2) >= 8 else 2

            buf_rows: List[List[str]] = []
            buf_budget = base_len
            row_start = 0
            part = 0

            def flush(end_idx: int) -> None:
                nonlocal buf_rows, buf_budget, row_start, part
                if not buf_rows:
                    return
                lines = [base]
                for rr in buf_rows:
                    lines.append(_row_kv(h2, rr))
                    val_line = _row_values_compact(rr)
                    if val_line:
                        lines.append(val_line)
                text = "\n".join([ln for ln in lines if ln.strip()]).strip()
                out.append(Chunk(block.page, block.page, 'table', text, {
                    'caption': caption,
                    'headers': h2,
                    'row_start': row_start,
                    'row_end': end_idx,
                    'row_count': row_count,
                    'col_count': col_count,
                    'is_wide_table': len(slices) > 1,
                    'table_part': part,
                    'table_id': table_id,
                    'col_slice': [cs, ce],
                    'slice_index': slice_idx,
                    'slice_total': len(slices),
                    'page_start': block.page,
                    'page_end': block.page,
                }))
                part += 1
                buf_rows = []
                buf_budget = base_len
                row_start = end_idx

            total_preview = base
            for rr in rows2:
                total_preview += '\n' + _row_kv(h2, rr)
            if len(total_preview) <= hard_max and len(total_preview) >= min_chars:
                lines = [base]
                for rr in rows2:
                    lines.append(_row_kv(h2, rr))
                    val_line = _row_values_compact(rr)
                    if val_line:
                        lines.append(val_line)
                out.append(Chunk(block.page, block.page, 'table', '\n'.join(lines).strip(), {
                    'caption': caption,
                    'headers': h2,
                    'row_start': 0,
                    'row_end': len(rows2),
                    'row_count': row_count,
                    'col_count': col_count,
                    'is_wide_table': len(slices) > 1,
                    'table_part': part,
                    'table_id': table_id,
                    'col_slice': [cs, ce],
                    'slice_index': slice_idx,
                    'slice_total': len(slices),
                    'page_start': block.page,
                    'page_end': block.page,
                }))
                continue

            for i, rr in enumerate(rows2):
                row_line = _row_kv(h2, rr)
                val_line = _row_values_compact(rr)
                add_b = _budget_len(row_line, ctx) + 1 + (_budget_len(val_line, ctx) + 1 if val_line else 0)
                if buf_rows and (buf_budget + add_b) > target and len(buf_rows) >= min_rows and buf_budget >= min_chars:
                    flush(i)
                buf_rows.append(rr)
                buf_budget += add_b
                if buf_budget > hard_max and len(buf_rows) >= min_rows:
                    flush(i + 1)
            flush(len(rows2))

        return _merge_small_tables(out, int(getattr(ctx, 'table_min_emit_chars', getattr(ctx, 'table_min_chars', 320))), int(ctx.table_hard_max_chars))
