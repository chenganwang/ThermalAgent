"""Versioned search lexing, not a unit converter or a physical validator.

Unversioned historical indexes must retain the exact legacy query tokenizer.
Changing the current algorithm or protected symbol policy requires a new version.
"""
from __future__ import annotations

import re
from services.ingest_service.chunking.pack import strip_packed_meta

LEGACY_TOKENIZER_VERSION = "legacy_ascii_cjk_global_v1"
CURRENT_TOKENIZER_VERSION = "thermal_lexical_v2"
SUPPORTED_TOKENIZER_VERSIONS = frozenset({LEGACY_TOKENIZER_VERSION, CURRENT_TOKENIZER_VERSION})
_LEGACY_WORD_RE = re.compile(r"[A-Za-z0-9_./+\-=]+")
_WORD_RE = re.compile(r"[+-]?[A-Za-z0-9_]+(?:[./+\-=][A-Za-z0-9_]+)*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# A lexical guard, not another engineering conversion registry. Preserve SI
# prefix/symbol case even for units not currently accepted by calculation tools.
_SI_PREFIXES = ("", "q", "r", "y", "z", "a", "f", "p", "n", "u", "m", "c", "d", "da", "h", "k", "M", "G", "T", "P", "E", "Z", "Y", "R", "Q")
_UNIT_BASES = ("m", "g", "s", "A", "K", "mol", "cd", "rad", "sr", "Hz", "N", "Pa", "J", "W", "C", "V", "F", "Ohm", "S", "Wb", "T", "H", "lm", "lx", "Bq", "Gy", "Sv", "kat", "L", "l", "eV", "bar", "cal", "Cal")
_PROTECTED_SYMBOLS = frozenset(prefix+unit for prefix in _SI_PREFIXES for unit in _UNIT_BASES) | frozenset({"degC", "degF", "min", "psi", "rpm", "LPM", "kgK", "mK", "Btu"})


def require_tokenizer_version(value: object) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_TOKENIZER_VERSIONS:
        raise ValueError(f"Unsupported BM25 tokenizer version: {value!r}")
    return value


def _normalize_word(word: str) -> str:
    # Numeric identifiers, compounds, short symbols and unknown mixed-case
    # notation remain exact (800mW, 1e-3m, K/W, Psi_CA, mFoo). Plain lexical
    # words/acronyms such as Pump/PUMP and CPU/cpu are case-insensitive.
    if word in _PROTECTED_SYMBOLS or not re.fullmatch(r"[A-Za-z]{3,}", word):
        return word
    return word.lower() if word.islower() or word.isupper() or word.istitle() else word


def bm25_tokenize(text: str, *, version: str = CURRENT_TOKENIZER_VERSION) -> list[str]:
    version = require_tokenizer_version(version)
    cleaned = strip_packed_meta((text or "").strip())
    if version == LEGACY_TOKENIZER_VERSION:
        words = _LEGACY_WORD_RE.findall(cleaned)
        cjk = re.findall(r"[\u4e00-\u9fff]", cleaned)
        return words + ["".join(cjk[i:i+2]) for i in range(len(cjk)-1)]
    words = [_normalize_word(word) for word in _WORD_RE.findall(cleaned)]
    return words + [run[i:i+2] for run in _CJK_RUN_RE.findall(cleaned) for i in range(len(run)-1)]
