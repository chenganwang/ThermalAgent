from __future__ import annotations

import re
from typing import List, Tuple

from .base import ChunkStrategy
from ..types import Block, Chunk, ChunkContext
from ..normalize import (
    normalize_whitespace,
    normalize_units,
    repair_ocr_paragraph_lines,
    looks_formulaish,
    looks_list_item,
)
from ..semantic import semantic_break_before_indices


def _normalize(s: str) -> str:
    s = normalize_whitespace(normalize_units(s or ""))
    return s.strip()


def approx_tokens(text: str) -> int:
    if not text:
        return 0
    t = text.strip()
    cjk = len(re.findall(r"[一-鿿]", t))
    words = len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", t))
    nums = len(re.findall(r"\d+(?:\.\d+)?", t))
    letters_len = sum(len(m) for m in re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", t))
    nums_len = sum(len(m) for m in re.findall(r"\d+(?:\.\d+)?", t))
    sym = max(0, len(t) - cjk - letters_len - nums_len)
    return int(cjk + words + nums + sym * 0.2)


def _budget_len(text: str, ctx: ChunkContext) -> int:
    return approx_tokens(text) if ctx.use_token_budget else len(text)


def _hard_char_limit(ctx: ChunkContext) -> int:
    return int(getattr(ctx, "text_hard_max_chars", 1400))


def _norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^0-9a-z一-鿿 ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_near_duplicate(a: str, b: str) -> bool:
    ka = _norm_key(a)
    kb = _norm_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    shorter = min(len(ka), len(kb))
    longer = max(len(ka), len(kb))
    return shorter >= 16 and (ka in kb or kb in ka) and shorter / max(1, longer) >= 0.8


def _split_paragraphs(s: str) -> List[str]:
    normalized = _normalize(s)
    parts = [repair_ocr_paragraph_lines(p.strip()) for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    if not parts:
        parts = [repair_ocr_paragraph_lines(ln.strip()) for ln in normalized.split("\n") if ln.strip()]
    out: List[str] = []
    for p in parts:
        if out and _is_near_duplicate(out[-1], p):
            continue
        out.append(p)
    return out


_SENT_SPLIT = re.compile(r"(?<=[。！？；!?])\s+|\n+")


def _split_sentences(p: str) -> List[str]:
    p = repair_ocr_paragraph_lines((p or "").strip())
    if not p:
        return []
    raw = [x.strip() for x in _SENT_SPLIT.split(p) if x.strip()]
    out: List[str] = []
    for s in raw:
        if out and (len(s) < 8 or looks_formulaish(s)):
            out[-1] = (out[-1].rstrip() + " " + s).strip()
        else:
            if out and _is_near_duplicate(out[-1], s):
                continue
            out.append(s)
    return out


def _looks_like_heading(p: str, ctx: ChunkContext) -> Tuple[bool, int]:
    t = repair_ocr_paragraph_lines((p or "").strip())
    if not t:
        return False, 0
    if looks_formulaish(t) or looks_list_item(t):
        return False, 0
    if len(t) > ctx.heading_max_chars:
        return False, 0
    if re.search(r"[。！？!?]$", t):
        return False, 0
    m = re.match(r"^\s*(\d+(?:\.\d+)*)\s+(.+)$", t)
    if m:
        level = m.group(1).count(".") + 1
        return True, max(1, min(level, 6))
    if re.match(r"^\s*第[一二三四五六七八九十百千0-9]+[章节篇]", t):
        return True, 1
    if re.match(r"^\s*(摘要|引言|结论|参考文献|致谢|附录|题解|分析|讨论|计算)\b", t):
        return True, 1
    if len(t) <= 24 and " " not in t and "\n" not in t:
        return True, 2
    return False, 0


def _semantic_breaks_for_paragraphs(paragraphs: List[str], ctx: ChunkContext) -> set[int]:
    return semantic_break_before_indices(
        paragraphs,
        enabled=bool(getattr(ctx, "semantic_split_enable", False)),
        model_name=str(getattr(ctx, "semantic_model_name", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")),
        window_size=int(getattr(ctx, "semantic_window_size", 1)),
        percentile=float(getattr(ctx, "semantic_breakpoint_percentile", 85.0)),
        min_distance=float(getattr(ctx, "semantic_min_distance", 0.18)),
        min_part_chars=int(getattr(ctx, "semantic_min_part_chars", 12)),
    )


def _semantic_breaks_for_sentences(sentences: List[str], ctx: ChunkContext) -> set[int]:
    return semantic_break_before_indices(
        sentences,
        enabled=bool(getattr(ctx, "semantic_split_enable", False)),
        model_name=str(getattr(ctx, "semantic_model_name", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")),
        window_size=int(getattr(ctx, "semantic_window_size", 1)),
        percentile=float(getattr(ctx, "semantic_breakpoint_percentile", 85.0)),
        min_distance=float(getattr(ctx, "semantic_min_distance", 0.18)),
        min_part_chars=int(getattr(ctx, "semantic_min_part_chars", 12)),
    )


def _sections_compatible(a: Chunk, b: Chunk) -> bool:
    sa = (a.meta or {}).get("section_path")
    sb = (b.meta or {}).get("section_path")
    if not sa or not sb:
        return True
    return sa == sb


def _pages_touch(a: Chunk, b: Chunk) -> bool:
    return int(b.page_start) <= int(a.page_end) + 1


def _merge_small_text_chunks(chunks: List[Chunk], ctx: ChunkContext) -> List[Chunk]:
    if not chunks:
        return chunks
    min_emit = int(getattr(ctx, "text_min_emit_chars", 220))
    hard_max = int(getattr(ctx, "text_hard_max_chars", 1400))
    if min_emit <= 0:
        return chunks

    def can_merge(a: Chunk, b: Chunk) -> bool:
        if a.type != "text" or b.type != "text":
            return False
        if not _sections_compatible(a, b):
            return False
        if not _pages_touch(a, b):
            return False
        merged_len = len((a.text.rstrip() + "\n\n" + b.text.lstrip()).strip())
        return merged_len <= int(hard_max * 1.15)

    items = [Chunk(c.page_start, c.page_end, c.type, c.text, dict(c.meta or {})) for c in chunks]
    i = 0
    while i < len(items):
        cur = items[i]
        if cur.type != "text" or len((cur.text or "").strip()) >= min_emit:
            i += 1
            continue
        merged = False
        if i > 0 and can_merge(items[i - 1], cur):
            items[i - 1].text = (items[i - 1].text.rstrip() + "\n\n" + cur.text.lstrip()).strip()
            items[i - 1].page_end = max(items[i - 1].page_end, cur.page_end)
            if cur.meta:
                items[i - 1].meta = {**(items[i - 1].meta or {}), **cur.meta}
            items.pop(i)
            merged = True
        elif i + 1 < len(items) and can_merge(cur, items[i + 1]):
            items[i + 1].text = (cur.text.rstrip() + "\n\n" + items[i + 1].text.lstrip()).strip()
            items[i + 1].page_start = min(cur.page_start, items[i + 1].page_start)
            if cur.meta:
                items[i + 1].meta = {**(cur.meta or {}), **(items[i + 1].meta or {})}
            items.pop(i)
            merged = True
        if not merged:
            i += 1
    return items


class TextStrategy(ChunkStrategy):
    def supports(self, block: Block) -> bool:
        return block.type == "text"

    def chunk(self, block: Block, ctx: ChunkContext) -> List[Chunk]:
        text = _normalize(block.text)
        if not text:
            return []

        budget = ctx.text_chunk_chars
        overlap_budget = ctx.text_overlap_chars
        hard_char_budget = _hard_char_limit(ctx)
        semantic_trigger_chars = int(getattr(ctx, "semantic_trigger_chars", 320))
        semantic_min_chunk_chars = int(getattr(ctx, "semantic_min_chunk_chars", 240))

        page_end = int(block.meta.get("page_end", block.page))
        order_start = int(block.meta.get("order_start", block.order))
        order_end = int(block.meta.get("order_end", block.order))

        out: List[Chunk] = []
        buf: List[str] = []
        buf_has_fresh_content = False
        section_path: List[str] = []
        pending_headings: List[str] = []

        def make_meta(extra: dict | None = None) -> dict:
            m = {
                "page_start": block.page,
                "page_end": page_end,
                "order_start": order_start,
                "order_end": order_end,
            }
            if section_path:
                m["section_path"] = list(section_path)
            if extra:
                m.update(extra)
            return m

        def _current_buf_len() -> int:
            current_text = "\n\n".join(buf).strip()
            return _budget_len(current_text, ctx) if current_text else 0

        def _set_overlap_tail() -> None:
            nonlocal buf, buf_has_fresh_content
            if overlap_budget > 0 and buf:
                tail: List[str] = []
                tail_budget = 0
                for p in reversed(buf):
                    tail.insert(0, p)
                    tail_budget += _budget_len(p, ctx) + 1
                    if tail_budget >= overlap_budget:
                        break
                buf = tail
                buf_has_fresh_content = False
            else:
                buf = []
                buf_has_fresh_content = False

        def flush(*, final: bool = False) -> None:
            nonlocal buf, buf_has_fresh_content
            if not buf:
                return
            if final and not buf_has_fresh_content:
                buf = []
                buf_has_fresh_content = False
                return
            deduped: List[str] = []
            for x in buf:
                if deduped and _is_near_duplicate(deduped[-1], x):
                    continue
                deduped.append(x)
            body = "\n\n".join(deduped).strip()
            if body:
                out.append(Chunk(block.page, page_end, "text", body, make_meta()))
            if final:
                buf = []
                buf_has_fresh_content = False
            else:
                _set_overlap_tail()

        def emit_heading(h: str, level: int) -> None:
            nonlocal section_path, pending_headings
            while len(section_path) < level:
                section_path.append("")
            section_path = section_path[:level]
            section_path[-1] = h.strip()
            pending_headings.append(h.strip())
            if ctx.heading_as_chunk:
                out.append(Chunk(block.page, page_end, "text", h.strip(), make_meta({"is_heading": True, "heading_level": level})))

        def add_piece(piece: str) -> None:
            nonlocal buf, buf_has_fresh_content, pending_headings
            piece = piece.strip()
            if not piece:
                return
            if pending_headings:
                piece = "\n".join(pending_headings + [piece])
                pending_headings = []
            if buf and _is_near_duplicate(buf[-1], piece):
                return
            current_text = "\n\n".join(buf).strip()
            merged = (current_text + "\n\n" + piece).strip() if current_text else piece
            if (_budget_len(merged, ctx) > budget) or (len(merged) > hard_char_budget):
                flush(final=False)
            buf.append(piece)
            buf_has_fresh_content = True

        paragraphs = _split_paragraphs(text)
        para_breaks = _semantic_breaks_for_paragraphs(paragraphs, ctx)

        for idx, p in enumerate(paragraphs):
            is_h, level = _looks_like_heading(p, ctx)
            if is_h:
                current = "\n\n".join(buf).strip()
                if current and (_budget_len(current, ctx) >= int(budget * 0.72) or len(current) >= int(hard_char_budget * 0.72)):
                    flush(final=True)
                emit_heading(p, level)
                continue

            if idx in para_breaks and _current_buf_len() >= max(semantic_trigger_chars, semantic_min_chunk_chars):
                flush(final=True)

            if _budget_len(p, ctx) > budget or len(p) > hard_char_budget:
                if pending_headings:
                    p = "\n".join(pending_headings + [p])
                    pending_headings = []
                flush(final=True)
                sents = _split_sentences(p)
                if not sents:
                    raw = p
                    step = max(1, min(int(budget), hard_char_budget))
                    s = 0
                    while s < len(raw):
                        e = min(len(raw), s + step)
                        piece = raw[s:e].strip()
                        if piece:
                            out.append(Chunk(block.page, page_end, "text", piece, make_meta({"split_from_long_paragraph": True})))
                        s = max(0, e - max(0, int(overlap_budget)))
                    continue
                sent_buf: List[str] = []
                sent_breaks = _semantic_breaks_for_sentences(sents, ctx)

                def _sent_buf_len() -> int:
                    current = " ".join(sent_buf).strip()
                    return _budget_len(current, ctx) if current else 0

                def flush_sent(*, final: bool = False) -> None:
                    nonlocal sent_buf
                    if not sent_buf:
                        return
                    body = " ".join(sent_buf).strip()
                    if body:
                        out.append(Chunk(block.page, page_end, "text", body, make_meta({"split_from_long_paragraph": True})))
                    if final:
                        sent_buf = []
                    else:
                        keep: List[str] = []
                        keep_b = 0
                        for s2 in reversed(sent_buf):
                            keep.insert(0, s2)
                            keep_b += _budget_len(s2, ctx) + 1
                            if keep_b >= overlap_budget:
                                break
                        sent_buf = keep

                for s_idx, s in enumerate(sents):
                    if s_idx in sent_breaks and _sent_buf_len() >= max(semantic_trigger_chars, semantic_min_chunk_chars):
                        flush_sent(final=True)
                    if sent_buf and _is_near_duplicate(sent_buf[-1], s):
                        continue
                    current = " ".join(sent_buf).strip()
                    merged = (current + " " + s).strip() if current else s
                    if len(merged) > hard_char_budget or _budget_len(merged, ctx) > budget:
                        flush_sent(final=False)
                    sent_buf.append(s)
                flush_sent(final=True)
                continue

            add_piece(p)

        if pending_headings and buf:
            buf[-1] = "\n".join(pending_headings + [buf[-1]])
            pending_headings = []
        flush(final=True)
        return _merge_small_text_chunks(out, ctx)
