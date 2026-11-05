from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List

from .types import Chunk

_WS_RE = re.compile(r"\s+")


def _norm_for_dedup(s: str) -> str:
    s = (s or "").strip().lower()
    s = _WS_RE.sub(" ", s)
    s = re.sub(r"[^0-9a-z一-鿿 ]+", " ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _tokenize_for_simhash(s: str) -> List[str]:
    out: List[str] = []
    if not s:
        return out
    out.extend(re.findall(r"[0-9a-z]+", s.lower()))
    out.extend(re.findall(r"[一-鿿]", s))
    return out


def _stable_hash64(token: str) -> int:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _simhash64(tokens: List[str]) -> int:
    v = [0] * 64
    for t in tokens:
        h = _stable_hash64(t)
        for i in range(64):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    out = 0
    for i in range(64):
        if v[i] >= 0:
            out |= (1 << i)
    return out


def _hamming64(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def symbol_ratio(s: str) -> float:
    s = s or ""
    if not s:
        return 1.0
    keep = re.findall(r"[0-9a-zA-Z一-鿿]", s)
    return 1.0 - (len(keep) / max(1, len(s)))


def _adjacent_overlap_ratio(a: str, b: str) -> float:
    na = _norm_for_dedup(a)
    nb = _norm_for_dedup(b)
    if not na or not nb:
        return 0.0
    shorter = min(len(na), len(nb))
    longer = max(len(na), len(nb))
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return shorter / max(1, longer)
    max_check = min(shorter, 200)
    for k in range(max_check, 19, -1):
        if na[-k:] == nb[:k]:
            return k / max(1, shorter)
    return 0.0


def _dedup_adjacent_segments(text: str) -> str:
    out: List[str] = []
    t = (text or "").strip()
    if not t:
        return t
    parts = [x.strip() for x in re.split(r"(?:\n{2,}|(?<=[。！？!?；;]))", t) if x and x.strip()]
    for p in parts:
        np = _norm_for_dedup(p)
        if not np:
            continue
        if out:
            prev = _norm_for_dedup(out[-1])
            if np == prev:
                continue
            shorter = min(len(np), len(prev))
            longer = max(len(np), len(prev))
            if shorter >= 16 and (np in prev or prev in np) and shorter / max(1, longer) >= 0.8:
                continue
        out.append(p)
    return "\n\n".join(out).strip()


def _is_tiny_heading_like(c: Chunk) -> bool:
    t = (c.text or '').strip()
    if c.type != 'text' or not t:
        return False
    if len(t) > 120:
        return False
    first = t.splitlines()[0].strip()
    if re.fullmatch(r"(?:题解|分析|讨论|计算|小结|例\d*|解|附录.*|第[一二三四五六七八九十百千0-9]+[章节篇].*)", first):
        return True
    if len(first) <= 24 and not re.search(r"[。！？!?]", first):
        return True
    return False


def _looks_page_artifact(text: str) -> bool:
    t = (text or '').strip()
    if not t:
        return True
    one = re.sub(r"\s+", " ", t)
    if re.fullmatch(r"\d{1,4}", one):
        return True
    if re.fullmatch(r"第?\s*\d+\s*页", one):
        return True
    if re.search(r"传热学（?第?6版）?", one) and re.search(r"\b\d{2,4}\b", one):
        return True
    if len(one) <= 24 and re.search(r"\b\d{2,4}\b", one) and not re.search(r"[。！？!?；;]", one):
        return True
    if len(one) <= 80 and re.search(r"^[A-Za-z0-9\-\._ ()（）]+$", one):
        return True
    return False


def _is_noise_like(c: Chunk, *, drop_page_artifacts: bool = True) -> bool:
    t = (c.text or '').strip()
    if not t:
        return True
    if drop_page_artifacts and _looks_page_artifact(t):
        return True
    if len(t) <= 20 and not re.search(r"[一-鿿A-Za-z]", t):
        return True
    zh = len(re.findall(r"[一-鿿]", t))
    alpha = len(re.findall(r"[A-Za-z]", t))
    digits = len(re.findall(r"\d", t))
    if len(t) < 80 and digits > max(zh + alpha, 0) * 2:
        return True
    if len(t) < 80 and symbol_ratio(t) > 0.55 and not re.search(r"[。；;]", t):
        return True
    return False


def _same_table(a: Chunk, b: Chunk) -> bool:
    if a.type != 'table' or b.type != 'table':
        return False
    ma, mb = a.meta or {}, b.meta or {}
    if ma.get('table_id') and ma.get('table_id') == mb.get('table_id'):
        return True
    if ma.get('caption') and ma.get('caption') == mb.get('caption'):
        return True
    return False


def _pages_touch(a: Chunk, b: Chunk) -> bool:
    return int(b.page_start) <= int(a.page_end) + 1


@dataclass
class QCConfig:
    min_chars: int = 50
    max_symbol_ratio: float = 0.65
    merge_below_chars: int = 180
    max_adjacent_hamming: int = 3
    text_min_chars: int | None = None
    table_min_chars: int | None = None
    figure_min_chars: int | None = None
    text_max_symbol_ratio: float | None = None
    table_max_symbol_ratio: float | None = None
    figure_max_symbol_ratio: float | None = None
    drop_page_artifacts: bool = True

    def min_chars_for(self, chunk_type: str) -> int:
        if chunk_type == "table":
            return int(self.table_min_chars if self.table_min_chars is not None else max(80, self.min_chars))
        if chunk_type == "figure":
            return int(self.figure_min_chars if self.figure_min_chars is not None else max(20, self.min_chars // 2))
        return int(self.text_min_chars if self.text_min_chars is not None else self.min_chars)

    def max_symbol_ratio_for(self, chunk_type: str) -> float:
        if chunk_type == "table":
            return float(self.table_max_symbol_ratio if self.table_max_symbol_ratio is not None else max(0.85, self.max_symbol_ratio))
        if chunk_type == "figure":
            return float(self.figure_max_symbol_ratio if self.figure_max_symbol_ratio is not None else max(0.80, self.max_symbol_ratio))
        return float(self.text_max_symbol_ratio if self.text_max_symbol_ratio is not None else self.max_symbol_ratio)


def apply_qc(chunks: List[Chunk], cfg: QCConfig) -> List[Chunk]:
    cleaned: List[Chunk] = []
    for c in chunks:
        c.text = _dedup_adjacent_segments(c.text)
        cleaned.append(c)

    filtered: List[Chunk] = []
    for c in cleaned:
        t = (c.text or '').strip()
        if not t:
            continue
        if len(t) < cfg.min_chars_for(c.type):
            if _is_noise_like(c, drop_page_artifacts=cfg.drop_page_artifacts):
                continue
        if symbol_ratio(t) > cfg.max_symbol_ratio_for(c.type):
            continue
        filtered.append(c)
    if not filtered:
        return []

    absorbed: List[Chunk] = []
    i = 0
    while i < len(filtered):
        c = filtered[i]
        if _is_noise_like(c, drop_page_artifacts=cfg.drop_page_artifacts):
            i += 1
            continue
        if _is_tiny_heading_like(c) and i + 1 < len(filtered):
            nxt = filtered[i + 1]
            if nxt.type in ('text', 'table') and _pages_touch(c, nxt):
                nxt.text = (c.text.rstrip() + '\n' + nxt.text.lstrip()).strip()
                if c.meta:
                    nxt.meta = {**(c.meta or {}), **(nxt.meta or {})}
                i += 1
                continue
        if c.type == 'table' and len(c.text) < cfg.min_chars_for('table') and i + 1 < len(filtered) and _same_table(c, filtered[i + 1]):
            nxt = filtered[i + 1]
            nxt.text = (c.text.rstrip() + '\n' + nxt.text.lstrip()).strip()
            nxt.page_start = min(c.page_start, nxt.page_start)
            if c.meta:
                nxt.meta = {**(c.meta or {}), **(nxt.meta or {})}
            i += 1
            continue
        absorbed.append(c)
        i += 1

    merged: List[Chunk] = []
    buf: Chunk | None = None
    for c in absorbed:
        if buf is None:
            buf = c
            continue
        can_merge = False
        if buf.type == 'text' and c.type == 'text' and _pages_touch(buf, c) and (len(buf.text) < cfg.min_chars_for('text') or len(c.text) < cfg.min_chars_for('text')):
            can_merge = True
        elif buf.type == 'table' and c.type == 'table' and _same_table(buf, c) and _pages_touch(buf, c) and (len(buf.text) < cfg.min_chars_for('table') or len(c.text) < cfg.min_chars_for('table')):
            can_merge = True
        if can_merge and _adjacent_overlap_ratio(buf.text, c.text) < 0.35:
            sep = '\n\n' if buf.type == 'text' else '\n'
            buf.text = _dedup_adjacent_segments((buf.text.rstrip() + sep + c.text.lstrip()).strip())
            buf.page_end = max(buf.page_end, c.page_end)
            if c.meta:
                buf.meta = {**(buf.meta or {}), **c.meta}
            continue
        merged.append(buf)
        buf = c
    if buf is not None:
        merged.append(buf)

    deduped: List[Chunk] = []
    prev_hash: int | None = None
    prev_norm: str | None = None
    for c in merged:
        n = _norm_for_dedup(c.text)
        if not n:
            continue
        h = _simhash64(_tokenize_for_simhash(n))
        if prev_hash is not None and prev_norm is not None:
            if n == prev_norm:
                continue
            if _hamming64(h, prev_hash) <= cfg.max_adjacent_hamming:
                continue
        deduped.append(c)
        prev_hash = h
        prev_norm = n
    return deduped
