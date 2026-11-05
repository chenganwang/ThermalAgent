"""Bound document token windows and pool them into one vector per source chunk.

The caller supplies an already loaded local SentenceTransformer. This module
does not download models, change model limits, access a database or write files.
"""
from __future__ import annotations

from typing import Any, Sequence
import numpy as np


def token_windows(token_count: int, budget: int, overlap: int) -> list[tuple[int, int, float]]:
    if budget <= 0 or not 0 <= overlap < budget:
        raise ValueError("window overlap must be smaller than the positive content budget")
    if token_count <= 0:
        raise ValueError("cannot embed an empty document chunk")
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + budget, token_count)
        spans.append((start, end))
        if end == token_count:
            break
        start += budget - overlap
    coverage = np.zeros(token_count, dtype=np.int32)
    for start, end in spans:
        coverage[start:end] += 1
    # Each original content token has total weight one across overlapping views.
    return [(start, end, float(np.sum(1.0 / coverage[start:end]))) for start, end in spans]


class WindowedDocumentEmbedder:
    def __init__(self, model: Any, *, overlap: int = 24, batch_size: int = 4, normalize: bool = True):
        if not normalize:
            raise ValueError("window pooling requires a normalized query/index embedding contract")
        self.model = model
        self.tokenizer = model.tokenizer
        self.max_length = int(model.max_seq_length)
        self.special_tokens = int(self.tokenizer.num_special_tokens_to_add(pair=False))
        self.budget = self.max_length - self.special_tokens
        self.overlap = int(overlap)
        token_windows(1, self.budget, self.overlap)
        if batch_size < 1:
            raise ValueError("window batch size must be positive")
        self.batch_size = int(batch_size)
        self.normalize = bool(normalize)
        self.statistics = {"chunks": 0, "windows": 0, "multi_window_chunks": 0, "content_tokens": 0}

    @property
    def policy(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0", "document_strategy": "token_window_weighted_mean_v1",
            "query_strategy": "model_default_single", "model_max_seq_length": self.max_length,
            "special_tokens": self.special_tokens, "content_token_budget": self.budget,
            "overlap_tokens": self.overlap, "window_weight": "sum_inverse_token_coverage",
            "window_l2_normalized": True, "aggregate_l2_normalized": self.normalize,
            "logical_vectors_per_chunk": 1,
        }

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        import torch

        dimension = int(self.model.get_sentence_embedding_dimension())
        sums = np.zeros((len(texts), dimension), dtype=np.float64)
        weights = np.zeros(len(texts), dtype=np.float64)
        pending: list[tuple[int, float, dict]] = []

        def flush() -> None:
            if not pending:
                return
            features = self.tokenizer.pad([item[2] for item in pending], padding=True, return_tensors="pt")
            features = {key: value.to(self.model.device) for key, value in features.items()}
            if int(features["input_ids"].shape[1]) > self.max_length:
                raise ValueError("prepared window exceeds the model token limit")
            with torch.inference_mode():
                vectors = self.model(features)["sentence_embedding"]
                vectors = torch.nn.functional.normalize(vectors, p=2, dim=1).cpu().numpy()
            if vectors.shape != (len(pending), dimension) or not np.isfinite(vectors).all():
                raise ValueError("model produced invalid document window vectors")
            for (owner, weight, _), vector in zip(pending, vectors):
                sums[owner] += weight * vector
                weights[owner] += weight
            pending.clear()

        self.model.eval()
        for owner, text in enumerate(texts):
            encoded = self.tokenizer(str(text), add_special_tokens=False, truncation=False,
                                     return_attention_mask=False, return_token_type_ids=False)
            ids = encoded["input_ids"]
            windows = token_windows(len(ids), self.budget, self.overlap)
            native_windows = None
            if not hasattr(self.tokenizer, "prepare_for_model"):
                # Transformers TokenizersBackend uses native Encoding instead of
                # the former prepare_for_model API. Keep IDs exact, without a
                # decode/retokenize round trip that can cross the token budget.
                encoding = encoded.encodings[0]
                encoding.truncate(self.budget, stride=self.overlap, direction="right")
                native_windows = [encoding, *encoding.overflowing]
                if len(native_windows) != len(windows):
                    raise ValueError("native token windows do not cover the planned content")
            self.statistics["chunks"] += 1
            self.statistics["windows"] += len(windows)
            self.statistics["content_tokens"] += len(ids)
            self.statistics["multi_window_chunks"] += int(len(windows) > 1)
            for position, (start, end, weight) in enumerate(windows):
                if native_windows is None:
                    features = self.tokenizer.prepare_for_model(ids[start:end], add_special_tokens=True,
                                                                truncation=False, return_attention_mask=True)
                else:
                    native = native_windows[position]
                    if native.ids != ids[start:end]:
                        raise ValueError("native window token IDs differ from the original content")
                    prepared = self.tokenizer.backend_tokenizer.post_process(native, add_special_tokens=True)
                    features = {"input_ids": prepared.ids, "attention_mask": prepared.attention_mask}
                    if "token_type_ids" in self.tokenizer.model_input_names:
                        features["token_type_ids"] = prepared.type_ids
                pending.append((owner, weight, features))
                if len(pending) >= self.batch_size:
                    flush()
        flush()
        if len(texts) == 0:
            return np.zeros((0, dimension), dtype=np.float32)
        vectors = sums / weights[:, None]
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.isfinite(vectors).all() or np.any(norms <= 1e-12):
            raise ValueError("document window pooling produced a non-finite or zero vector")
        if self.normalize:
            vectors = vectors / norms
        return np.asarray(vectors, dtype=np.float32)
