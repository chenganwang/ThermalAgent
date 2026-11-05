"""Read BM25 lexical contracts without depending on index managers or bundles.

Both active-generation resolution and the BM25 manager use this low-level loader.
It must not import either caller: bundle selection also calls manager validation.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

from .bm25_tokenizer import bm25_tokenize, LEGACY_TOKENIZER_VERSION, require_tokenizer_version


def load_bm25_payload(path, meta_path=None, *, expected_version=None, verify_tokens=True) -> tuple[dict, str]:
    """Read one artifact and its lexical contract; never rewrite legacy data."""
    path = Path(path)
    with path.open('rb') as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict):
        raise ValueError('BM25 artifact must be an object')
    version = require_tokenizer_version(payload.get('tokenizer_version', LEGACY_TOKENIZER_VERSION))
    metadata_path = Path(meta_path) if meta_path is not None else path.with_suffix(path.suffix + '.meta.json')
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if not isinstance(metadata, dict):
            raise ValueError('BM25 tokenizer metadata must be an object')
        if require_tokenizer_version(metadata.get('tokenizer_version', LEGACY_TOKENIZER_VERSION)) != version:
            raise ValueError('BM25 tokenizer payload/metadata versions differ')
    elif version != LEGACY_TOKENIZER_VERSION:
        raise ValueError('Versioned BM25 tokenizer metadata is missing')
    if expected_version is not None and require_tokenizer_version(expected_version) != version:
        raise ValueError('BM25 tokenizer artifact/build versions differ')
    ids, tokens, texts = (payload.get(key) for key in ('chunk_ids', 'tokenized_corpus', 'corpus_texts'))
    if not all(isinstance(items, list) for items in (ids, tokens, texts)) or not len(ids) == len(tokens) == len(texts):
        raise ValueError('BM25 artifact corpus lengths differ')
    if verify_tokens and tokens != [bm25_tokenize(text, version=version) for text in texts]:
        raise ValueError('BM25 tokenized corpus differs from its tokenizer contract')
    return payload, version
