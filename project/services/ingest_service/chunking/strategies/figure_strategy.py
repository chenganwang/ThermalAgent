from __future__ import annotations

from typing import List

from .base import ChunkStrategy
from ..types import Block, Chunk, ChunkContext
from ..normalize import normalize_cell_text


class FigureStrategy(ChunkStrategy):
    def supports(self, block: Block) -> bool:
        return block.type == "figure"

    def chunk(self, block: Block, ctx: ChunkContext) -> List[Chunk]:
        meta = dict(block.meta)
        caption = normalize_cell_text(meta.get("caption") or meta.get("alt_text") or "")
        body = normalize_cell_text(block.text or "")
        prev = normalize_cell_text(meta.get("prev_text") or "")

        parts: list[str] = []
        if caption:
            parts.append(f"[图注] {caption}")
        if prev:
            anchor = prev[-max(0, int(ctx.figure_anchor_chars)):].strip()
            if anchor and anchor not in body:
                parts.append(f"[图前文本锚点]\n{anchor}")
        if body:
            parts.append(body)

        text = "\n\n".join(p for p in parts if p.strip()).strip()
        if not text:
            return []
        return [Chunk(block.page, block.page, "figure", text, meta)]
