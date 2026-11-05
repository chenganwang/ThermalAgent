from __future__ import annotations

import json
import re

from .types import Chunk

# Remove packed meta from stored text before embedding
_META_RE = re.compile(r"\n?\[META\].*?\[/META\]\s*$", re.DOTALL)
_TYPE_RE = re.compile(r"^\[CHUNK_TYPE=[A-Z_]+\]\s*\n?", re.MULTILINE)

# NEW: remove raw formula blocks from embedding text (A档)
_FORMULA_RAW_RE = re.compile(r"\[FORMULA_RAW\].*?\[/FORMULA_RAW\]", re.DOTALL)


def strip_packed_meta(text: str) -> str:
    """Remove pack() headers/meta and noisy raw formula blocks before embedding.

    Order matters:
      1) remove [CHUNK_TYPE=...]
      2) remove [FORMULA_RAW]...[/FORMULA_RAW] (keep [FORMULA_NORM] for retrieval)
      3) remove trailing [META]{...}[/META]
    """
    s = (text or "")
    s = _TYPE_RE.sub("", s, count=1)
    s = _FORMULA_RAW_RE.sub("", s)
    s = _META_RE.sub("", s)
    return s.strip()


def pack_chunk_text(chunk: Chunk, *, include_meta: bool = True, include_type_header: bool = True) -> str:
    """Pack chunk into a single text field for DB storage (backward compatible)."""
    body = (chunk.text or "").strip()
    header = f"[CHUNK_TYPE={chunk.type.upper()}]" if include_type_header else ""
    if include_meta and chunk.meta:
        meta_str = json.dumps(chunk.meta, ensure_ascii=False, separators=(",", ":"))
        parts = [p for p in (header, body, f"[META]{meta_str}[/META]") if p]
        return "\n".join(parts)
    parts = [p for p in (header, body) if p]
    return "\n".join(parts)