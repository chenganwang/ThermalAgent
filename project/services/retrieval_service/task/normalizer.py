from __future__ import annotations

import re


_FULLWIDTH_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "？": "?",
        "！": "!",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
    }
)


def normalize_query(query: str) -> str:
    """Normalize spacing and punctuation without changing user meaning."""

    text = (query or "").strip().translate(_FULLWIDTH_TRANSLATION)
    text = re.sub(r"\s+", " ", text)
    return text


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(term.lower() in lowered for term in terms)
