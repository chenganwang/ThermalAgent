from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import numpy as np

from ..config import AppConfig


def l2_normalize(v: np.ndarray) -> np.ndarray:
    if v.ndim != 2:
        raise ValueError("embeddings must be a 2D numpy array")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


@lru_cache(maxsize=8)
def get_embedder(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        return ("sentence_transformers", SentenceTransformer(model_name))
    except Exception:
        try:
            from langchain_huggingface import HuggingFaceEmbeddings  # type: ignore
        except Exception:
            from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore
        return ("langchain", HuggingFaceEmbeddings(model_name=model_name))


def embed_texts_by_model(model_name: str, texts: Sequence[str], *, normalize: bool = True) -> np.ndarray:
    cleaned = [str(t or "").strip() for t in texts]
    if not cleaned:
        return np.zeros((0, 0), dtype="float32")

    provider_kind, provider = get_embedder(model_name)
    if provider_kind == "sentence_transformers":
        return np.asarray(
            provider.encode(
                cleaned,
                normalize_embeddings=normalize,
                show_progress_bar=False,
                batch_size=min(64, max(8, len(cleaned))),
            ),
            dtype="float32",
        )

    vectors = provider.embed_documents(list(cleaned))
    arr = np.asarray(vectors, dtype="float32")
    if normalize:
        arr = l2_normalize(arr)
    return arr


def embed_texts(cfg: AppConfig, texts: Sequence[str], *, normalize: bool | None = None) -> np.ndarray:
    do_normalize = cfg.embedding.normalize if normalize is None else bool(normalize)
    return embed_texts_by_model(cfg.embedding.model_name, texts, normalize=do_normalize)
