from __future__ import annotations

from typing import Any


SUPPORTED_ERROR_TYPES = {
    "annotation_incomplete",
    "annotation_incorrect",
    "multiple_valid_answers",
    "chunk_granularity_error",
    "source_noise_error",
    "bm25_keyword_collision",
    "dense_semantic_confusion",
    "fusion_amplification_error",
    "document_duplication_error",
    "query_under_specification",
    "negative_rejection_failure",
    "correct_but_outside_top_k",
    "retrieval_failure",
    "ranking_failure",
    "mapping_or_manifest_error",
    "unknown",
}


def _suggestion(error_type: str, confidence: str, *evidence: str) -> dict[str, Any]:
    if error_type not in SUPPORTED_ERROR_TYPES:
        raise ValueError(f"unsupported retrieval error type: {error_type}")
    return {
        "type": error_type,
        "confidence": confidence,
        "evidence": [item for item in evidence if item],
    }


def classify_case_diagnostic(
    diagnostic: dict[str, Any],
    *,
    target_k: int = 3,
) -> dict[str, Any]:
    modes = dict(diagnostic.get("modes") or {})
    hybrid = dict(modes.get("hybrid") or {})
    results = list(hybrid.get("results") or [])
    presence = dict(diagnostic.get("candidate_presence") or {})
    category = str(diagnostic.get("category") or diagnostic.get("corpus_scope") or "")
    answerable = bool(diagnostic.get("answerable", True))
    forbidden_documents = {
        int(item) for item in diagnostic.get("must_not_return_document_ids") or []
    }
    forbidden_top = [
        item
        for item in results[:target_k]
        if int(item.get("document_id") or -1) in forbidden_documents
    ]
    hit_target = bool(hybrid.get(f"hit_at_{target_k}"))
    suggestions: list[dict[str, Any]] = []

    if int(diagnostic.get("invalid_mapping_count") or 0) > 0:
        suggestions.append(
            _suggestion(
                "mapping_or_manifest_error",
                "high",
                f"invalid_mapping_count={diagnostic.get('invalid_mapping_count')}",
            )
        )

    if category in {"negative", "confusion_negative"} and forbidden_top:
        suggestions.append(
            _suggestion(
                "negative_rejection_failure",
                "high",
                "forbidden document appeared in hybrid target top-k",
                f"forbidden_document_ids={sorted(forbidden_documents)}",
            )
        )
    elif not answerable and results:
        suggestions.append(
            _suggestion(
                "negative_rejection_failure",
                "medium",
                "unanswerable case still produced ranked sources",
            )
        )

    if answerable and not hit_target:
        any_retriever_top10 = any(
            bool(presence.get(key))
            for key in ("faiss_top_10", "bm25_top_10", "hybrid_top_10")
        )
        if not any_retriever_top10:
            suggestions.append(
                _suggestion(
                    "retrieval_failure",
                    "high",
                    "no expected or acceptable chunk entered FAISS, BM25, or Hybrid top-10",
                )
            )
        else:
            suggestions.append(
                _suggestion(
                    "ranking_failure",
                    "high",
                    "expected or acceptable chunk entered a top-10 candidate list but missed target top-k",
                )
            )
            if hybrid.get("first_relevant_rank"):
                suggestions.append(
                    _suggestion(
                        "correct_but_outside_top_k",
                        "high",
                        f"first_relevant_rank={hybrid.get('first_relevant_rank')}",
                    )
                )

    top = results[0] if results else None
    if top and not bool(top.get("is_acceptable_chunk")):
        faiss_rank = top.get("faiss_rank")
        bm25_rank = top.get("bm25_rank")
        if bm25_rank is not None and int(bm25_rank) <= 3 and (
            faiss_rank is None or int(faiss_rank) > 5
        ):
            suggestions.append(
                _suggestion(
                    "bm25_keyword_collision",
                    "medium",
                    f"wrong_top_bm25_rank={bm25_rank}",
                    f"wrong_top_faiss_rank={faiss_rank}",
                )
            )
        if faiss_rank is not None and int(faiss_rank) <= 3 and (
            bm25_rank is None or int(bm25_rank) > 5
        ):
            suggestions.append(
                _suggestion(
                    "dense_semantic_confusion",
                    "medium",
                    f"wrong_top_faiss_rank={faiss_rank}",
                    f"wrong_top_bm25_rank={bm25_rank}",
                )
            )
        if (
            faiss_rank is not None
            and bm25_rank is not None
            and 3 < int(faiss_rank) <= 10
            and 3 < int(bm25_rank) <= 10
        ):
            suggestions.append(
                _suggestion(
                    "fusion_amplification_error",
                    "medium",
                    f"wrong_top_faiss_rank={faiss_rank}",
                    f"wrong_top_bm25_rank={bm25_rank}",
                    "wrong result rose to Hybrid rank 1",
                )
            )
        if bool(top.get("is_expected_document")) and not bool(top.get("is_acceptable_chunk")):
            suggestions.append(
                _suggestion(
                    "annotation_incomplete",
                    "low",
                    "top result is from an expected document but its chunk is not annotated acceptable",
                    "requires human annotation review",
                )
            )
        noise_flags = list(top.get("heuristic_noise_flags") or [])
        if noise_flags:
            suggestions.append(
                _suggestion(
                    "source_noise_error",
                    "medium",
                    "wrong top result has heuristic noise flags",
                    ",".join(noise_flags),
                )
            )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        if suggestion["type"] not in seen:
            seen.add(suggestion["type"])
            unique.append(suggestion)
    failed = bool(unique) or (answerable and not hit_target)
    if failed and not unique:
        unique.append(_suggestion("unknown", "low", "automatic rules were inconclusive"))
    return {
        "case_id": diagnostic.get("case_id"),
        "status": "failed" if failed else "passed",
        "suggested_error_types": unique,
        "human_error_type": None,
        "human_reviewed": False,
        "classification_type": "deterministic_rule_suggestion",
        "target_k": target_k,
    }
