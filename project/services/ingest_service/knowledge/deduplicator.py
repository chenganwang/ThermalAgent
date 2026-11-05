from __future__ import annotations

from .contracts import KnowledgeUnitCandidate


def _source_count(candidate: KnowledgeUnitCandidate) -> int:
    try:
        return int((candidate.source or {}).get("merged_source_count") or 1)
    except Exception:
        return 1


def deduplicate_candidates(candidates: list[KnowledgeUnitCandidate]) -> list[KnowledgeUnitCandidate]:
    best_by_key: dict[str, KnowledgeUnitCandidate] = {}
    order: list[str] = []

    for candidate in candidates or []:
        key = (candidate.dedup_key or "").strip()
        if not key:
            key = f"missing:{len(order)}"
            candidate.dedup_key = key
        if key not in best_by_key:
            best_by_key[key] = candidate
            order.append(key)
            candidate.source["merged_source_count"] = _source_count(candidate)
            continue

        existing = best_by_key[key]
        merged_count = _source_count(existing) + _source_count(candidate)
        keep_new = float(candidate.confidence or 0.0) > float(existing.confidence or 0.0)
        kept = candidate if keep_new else existing
        kept.source["merged_source_count"] = merged_count
        if "duplicate_merged" not in kept.warnings:
            kept.warnings.append("duplicate_merged")
        best_by_key[key] = kept

    return [best_by_key[key] for key in order if key in best_by_key]
