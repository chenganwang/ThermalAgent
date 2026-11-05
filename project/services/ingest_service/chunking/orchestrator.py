from __future__ import annotations

from typing import List, Sequence
import hashlib
import re

from .rows import ChunkInsertRow
from .types import Block, Chunk, ChunkContext
from .strategies.text_strategy import TextStrategy, approx_tokens
from .strategies.table_strategy import TableStrategy
from .strategies.figure_strategy import FigureStrategy
from .qc import apply_qc, QCConfig

DEFAULT_STRATEGIES = (TextStrategy(), TableStrategy(), FigureStrategy())


def _content_hash(chunk_type: str, text: str) -> str:
    payload = f"{chunk_type}\n{text.strip()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _looks_noisy_section(s: str) -> bool:
    t = (s or "").strip()
    if not t or len(t) <= 2:
        return True
    letters = sum(ch.isalpha() for ch in t)
    digits = sum(ch.isdigit() for ch in t)
    if letters == 0 and digits > 0 and len(t) <= 20:
        return True
    if re.fullmatch(r"[A-Z0-9_\- ]{4,}", t):
        return True
    return False


def _section_path_text(meta: dict | None) -> str | None:
    if not meta:
        return None
    path = meta.get("section_path")
    if not path:
        return None
    if isinstance(path, str):
        text = path.strip() or None
        if text and not _looks_noisy_section(text):
            return text
        return None
    if isinstance(path, (list, tuple)):
        parts = []
        for x in path:
            s = str(x).strip()
            if s and not _looks_noisy_section(s):
                parts.append(s)
        return " > ".join(parts) if parts else None
    return None


def chunk_blocks_to_rows(blocks: List[Block], *, ctx: ChunkContext | None = None, strategies: Sequence = DEFAULT_STRATEGIES) -> List[ChunkInsertRow]:
    if ctx is None:
        ctx = ChunkContext()

    blocks = sorted(blocks, key=lambda b: (b.page, b.order))
    text_strat = next(s for s in strategies if isinstance(s, TextStrategy))
    other_strats = [s for s in strategies if not isinstance(s, TextStrategy)]

    chunks: List[Chunk] = []
    text_buf: List[Block] = []
    last_text_tail: str = ""

    def update_tail(s: str) -> None:
        nonlocal last_text_tail
        t = (s or "").strip()
        if not t:
            return
        keep = int(ctx.prev_text_tail_chars or 0)
        if keep <= 0:
            return
        last_text_tail = t[-keep:]

    def flush_text() -> None:
        nonlocal text_buf
        if not text_buf:
            return
        merged_text = "\n\n".join((b.text or "").strip() for b in text_buf if (b.text or "").strip()).strip()
        if not merged_text:
            text_buf = []
            return
        page_start = text_buf[0].page
        page_end = text_buf[-1].page
        order_start = text_buf[0].order
        order_end = text_buf[-1].order
        merged = Block(
            page=page_start,
            type="text",
            order=order_start,
            text=merged_text,
            meta={"page_end": page_end, "order_start": order_start, "order_end": order_end},
        )
        chunks.extend(text_strat.chunk(merged, ctx))
        update_tail(merged_text)
        text_buf = []

    merge_across_pages = bool(getattr(ctx, "merge_text_across_pages", False))

    for b in blocks:
        if b.type == "text":
            if (b.text or "").strip():
                if text_buf and (not merge_across_pages) and b.page != text_buf[-1].page:
                    flush_text()
                text_buf.append(b)
            continue
        flush_text()
        if last_text_tail and "prev_text" not in (b.meta or {}):
            b.meta["prev_text"] = last_text_tail
        strat = next((s for s in other_strats if s.supports(b)), None)
        if strat:
            chunks.extend(strat.chunk(b, ctx))

    flush_text()

    if ctx.enable_qc:
        qc_cfg = QCConfig(
            min_chars=ctx.qc_min_chars,
            max_symbol_ratio=ctx.qc_max_symbol_ratio,
            merge_below_chars=ctx.qc_merge_below_chars,
            max_adjacent_hamming=ctx.qc_max_adjacent_hamming,
            text_min_chars=ctx.qc_text_min_chars,
            table_min_chars=ctx.qc_table_min_chars,
            figure_min_chars=ctx.qc_figure_min_chars,
            text_max_symbol_ratio=ctx.qc_text_max_symbol_ratio,
            table_max_symbol_ratio=ctx.qc_table_max_symbol_ratio,
            figure_max_symbol_ratio=ctx.qc_figure_max_symbol_ratio,
            drop_page_artifacts=bool(getattr(ctx, 'qc_drop_page_artifacts', True)),
        )
        chunks = apply_qc(chunks, qc_cfg)

    rows: List[ChunkInsertRow] = []
    for idx, c in enumerate(chunks):
        text = (c.text or "").strip()
        if not text:
            continue
        rows.append(
            ChunkInsertRow(
                chunk_index=idx,
                page_start=c.page_start,
                page_end=c.page_end,
                chunk_type=c.type,
                text=text,
                char_len=len(text),
                token_len=approx_tokens(text),
                section_path=_section_path_text(c.meta),
                content_hash=_content_hash(c.type, text),
                quality_score=None,
                meta_json=c.meta or {},
                is_active=1,
            )
        )
    return rows
