from __future__ import annotations

import logging
from typing import List, Sequence, Set

import numpy as np

from services.retrieval_service.embeddings.provider import embed_texts_by_model

logger = logging.getLogger(__name__)


def _build_windows(parts: Sequence[str], window_size: int) -> List[str]:
    if not parts:
        return []
    size = max(0, int(window_size))
    windows: List[str] = []
    n = len(parts)
    for i in range(n):
        left = max(0, i - size)
        right = min(n, i + size + 1)
        windows.append(" ".join(x.strip() for x in parts[left:right] if x and x.strip()))
    return windows


def semantic_break_before_indices(
    parts: Sequence[str],
    *,
    enabled: bool,
    model_name: str,
    window_size: int = 1,
    percentile: float = 85.0,
    min_distance: float = 0.18,
    min_part_chars: int = 12,
) -> Set[int]:
    if not enabled:
        return set()

    cleaned = [((p or "").strip()) for p in parts]
    if len(cleaned) < 2:
        return set()

    valid_positions = [i for i, p in enumerate(cleaned) if len(p) >= int(min_part_chars)]
    if len(valid_positions) < 2:
        return set()

    seq = [cleaned[i] for i in valid_positions]
    windows = _build_windows(seq, int(window_size))
    try:
        vecs = embed_texts_by_model(model_name, windows, normalize=True)
    except Exception as e:
        logger.warning("semantic chunking disabled for current block; embed failed: %s", e)
        return set()

    if len(vecs) < 2:
        return set()

    sims = np.sum(vecs[:-1] * vecs[1:], axis=1)
    dists = 1.0 - sims
    if dists.size == 0:
        return set()

    dynamic = float(np.percentile(dists, float(percentile)))
    threshold = max(float(min_distance), dynamic)

    breaks: Set[int] = set()
    for j, dist in enumerate(dists):
        if float(dist) >= threshold:
            breaks.add(valid_positions[j + 1])
    return breaks
