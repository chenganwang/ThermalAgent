from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any
import math
import re

import numpy as np

from .error_taxonomy import classify_case_diagnostic


def _rounded_mean(values: list[float]) -> float:
    return round(float(mean(values)), 4) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    return round(float(np.percentile(values, percentile)), 4) if values else 0.0


def _result_ids(mode: dict[str, Any], key: str, k: int) -> list[int]:
    return [
        int(item[key])
        for item in mode.get("results") or []
        if int(item.get("rank") or 10**9) <= k and item.get(key) is not None
    ]


def _case_recall(expected: set[int], returned: list[int]) -> float:
    return len(expected & set(returned)) / len(expected) if expected else 1.0


def _case_precision(acceptable: set[int], returned: list[int], k: int) -> float:
    return len(acceptable & set(returned)) / float(k)


def compute_configuration_metrics(
    diagnostics: list[dict[str, Any]],
    *,
    mode_name: str,
) -> dict[str, Any]:
    answerable = [item for item in diagnostics if bool(item.get("answerable", True))]
    negative = [
        item
        for item in diagnostics
        if str(item.get("category") or item.get("corpus_scope") or "")
        in {"negative", "confusion_negative"}
        or str(item.get("corpus_scope") or "") == "confusion_negative"
    ]
    strict_by_k: dict[int, list[float]] = {k: [] for k in (1, 3, 5, 10)}
    acceptable_by_k: dict[int, list[float]] = {k: [] for k in (1, 3, 5, 10)}
    precision_by_k: dict[int, list[float]] = {k: [] for k in (1, 3, 5)}
    document_by_k: dict[int, list[float]] = {k: [] for k in (1, 3, 5, 10)}
    reciprocal: list[float] = []
    latencies: list[float] = []
    invalid_mappings = 0
    scope_strict_values: dict[str, list[float]] = {
        "legacy_protection": [],
        "new_external_source": [],
        "synonym_paraphrase": [],
    }
    scope_acceptable_values: dict[str, list[float]] = {
        "legacy_protection": [],
        "new_external_source": [],
        "synonym_paraphrase": [],
    }

    for item in diagnostics:
        mode = dict((item.get("modes") or {}).get(mode_name) or {})
        latencies.append(float(mode.get("latency_ms") or 0.0))
        invalid_mappings += int(item.get("invalid_mapping_count") or 0)
        if item not in answerable:
            continue
        expected = {int(value) for value in item.get("expected_chunk_ids") or []}
        acceptable = expected | {int(value) for value in item.get("acceptable_chunk_ids") or []}
        expected_docs = {int(value) for value in item.get("expected_document_ids") or []}
        acceptable_docs = expected_docs | {
            int(value) for value in item.get("acceptable_document_ids") or []
        }
        for k in (1, 3, 5, 10):
            returned = _result_ids(mode, "chunk_id", k)
            returned_docs = _result_ids(mode, "document_id", k)
            strict_by_k[k].append(_case_recall(expected, returned))
            acceptable_by_k[k].append(float(bool(acceptable & set(returned))))
            document_by_k[k].append(_case_recall(acceptable_docs, returned_docs))
            if k in precision_by_k:
                precision_by_k[k].append(_case_precision(acceptable, returned, k))
        first_rank = mode.get("first_relevant_rank")
        reciprocal.append(1.0 / int(first_rank) if first_rank else 0.0)
        scope = str(item.get("corpus_scope") or "")
        if scope in scope_strict_values:
            scope_strict_values[scope].append(strict_by_k[3][-1])
            scope_acceptable_values[scope].append(acceptable_by_k[3][-1])

    negative_flags: list[float] = []
    for item in negative:
        mode = dict((item.get("modes") or {}).get(mode_name) or {})
        forbidden = {int(value) for value in item.get("must_not_return_document_ids") or []}
        top3_docs = set(_result_ids(mode, "document_id", 3))
        negative_flags.append(float(bool(forbidden & top3_docs)))

    return {
        "mode": mode_name,
        "case_count": len(diagnostics),
        "answerable_case_count": len(answerable),
        "negative_case_count": len(negative),
        "strict_expected": {
            **{f"recall_at_{k}": _rounded_mean(strict_by_k[k]) for k in (1, 3, 5, 10)},
        },
        "acceptable": {
            **{f"recall_at_{k}": _rounded_mean(acceptable_by_k[k]) for k in (1, 3, 5, 10)},
            **{f"precision_at_{k}": _rounded_mean(precision_by_k[k]) for k in (1, 3, 5)},
            "mrr": _rounded_mean(reciprocal),
        },
        "document": {
            **{f"recall_at_{k}": _rounded_mean(document_by_k[k]) for k in (1, 3, 5, 10)},
        },
        "scope_recall_at_3": {
            "old_corpus": _rounded_mean(scope_strict_values["legacy_protection"]),
            "new_source": _rounded_mean(scope_strict_values["new_external_source"]),
            "paraphrase": _rounded_mean(scope_strict_values["synonym_paraphrase"]),
        },
        "scope_acceptable_hit_at_3": {
            "old_corpus": _rounded_mean(scope_acceptable_values["legacy_protection"]),
            "new_source": _rounded_mean(scope_acceptable_values["new_external_source"]),
            "paraphrase": _rounded_mean(scope_acceptable_values["synonym_paraphrase"]),
        },
        "negative_false_positive_rate": _rounded_mean(negative_flags),
        "average_latency_ms": _rounded_mean(latencies),
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "invalid_chunk_mapping_count": invalid_mappings,
        "human_validated": False,
        "expected_only_metrics": True,
        "sample_limited": True,
    }


def pair_bundle_diagnostics(
    review_cases: list[dict[str, Any]],
    old_diagnostics: list[dict[str, Any]],
    candidate_diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    old_by_id = {str(item.get("case_id")): item for item in old_diagnostics}
    candidate_by_id = {str(item.get("case_id")): item for item in candidate_diagnostics}
    output: list[dict[str, Any]] = []
    for review in review_cases:
        case_id = str(review.get("case_id"))
        old = old_by_id.get(case_id, {})
        candidate = candidate_by_id.get(case_id, {})
        rank_changes: dict[str, Any] = {}
        for mode_name in ("faiss", "bm25", "hybrid"):
            old_rank = ((old.get("modes") or {}).get(mode_name) or {}).get("first_relevant_rank")
            candidate_rank = ((candidate.get("modes") or {}).get(mode_name) or {}).get(
                "first_relevant_rank"
            )
            delta = None
            if old_rank is not None and candidate_rank is not None:
                delta = int(candidate_rank) - int(old_rank)
            rank_changes[mode_name] = {
                "old_rank": old_rank,
                "candidate_rank": candidate_rank,
                "rank_delta": delta,
                "old_hit_at_3": bool(old_rank and int(old_rank) <= 3),
                "candidate_hit_at_3": bool(candidate_rank and int(candidate_rank) <= 3),
            }
        output.append(
            {
                "case_id": case_id,
                "review_case": review,
                "old": old,
                "candidate": candidate,
                "rank_changes": rank_changes,
                "classification": classify_case_diagnostic(candidate),
            }
        )
    return output


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9_./+\-=]{2,}|[\u4e00-\u9fff]{2,}", str(text or "").lower())
    return set(words)


def keyword_overlap(query: str, text: str) -> list[str]:
    return sorted(_tokens(query) & _tokens(text))[:20]


def _primary_failure_type(classification: dict[str, Any]) -> str:
    types = [item.get("type") for item in classification.get("suggested_error_types") or []]
    if "retrieval_failure" in types:
        return "retrieval_failure"
    if "ranking_failure" in types:
        return "ranking_failure"
    return "unknown"


def build_old_query_regression_analysis(
    paired: list[dict[str, Any]],
    *,
    chunk_flags: dict[int, list[str]] | None = None,
) -> dict[str, Any]:
    chunk_flags = chunk_flags or {}
    cases: list[dict[str, Any]] = []
    for pair in paired:
        review = pair.get("review_case") or {}
        if str(review.get("category") or "") != "old_corpus" and str(
            review.get("corpus_scope") or ""
        ) != "legacy_protection":
            continue
        old_change = pair["rank_changes"]["hybrid"]
        degraded = bool(old_change["old_hit_at_3"] and not old_change["candidate_hit_at_3"])
        acceptable = {
            int(item)
            for item in list((pair.get("candidate") or {}).get("expected_chunk_ids") or [])
            + list((pair.get("candidate") or {}).get("acceptable_chunk_ids") or [])
        }
        candidate_hybrid = ((pair.get("candidate") or {}).get("modes") or {}).get("hybrid") or {}
        interference: list[dict[str, Any]] = []
        for item in list(candidate_hybrid.get("results") or [])[:3]:
            chunk_id = int(item.get("chunk_id") or -1)
            if chunk_id in acceptable:
                continue
            interference.append(
                {
                    "rank": item.get("rank"),
                    "chunk_id": chunk_id,
                    "document_id": item.get("document_id"),
                    "source_name": item.get("source_name"),
                    "faiss_rank": item.get("faiss_rank"),
                    "bm25_rank": item.get("bm25_rank"),
                    "keyword_overlap": keyword_overlap(
                        str((pair.get("candidate") or {}).get("query") or ""),
                        str(item.get("chunk_text_preview") or ""),
                    ),
                    "text_length": item.get("content_length"),
                    "heuristic_noise_flags": list(chunk_flags.get(chunk_id, [])),
                }
            )
        cases.append(
            {
                "case_id": pair.get("case_id"),
                "degraded_at_3": degraded,
                "old_correct_rank": old_change.get("old_rank"),
                "candidate_correct_rank": old_change.get("candidate_rank"),
                "rank_changes": pair.get("rank_changes"),
                "displacing_chunks": interference,
                "retrieval_or_ranking": _primary_failure_type(pair.get("classification") or {}),
                "human_validated": False,
            }
        )
    return {
        "old_case_count": len(cases),
        "degraded_case_count": sum(bool(case["degraded_at_3"]) for case in cases),
        "cases": cases,
        "human_validated": False,
        "analysis_type": "rule_based_diagnostic",
    }


def build_new_source_analysis(paired: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for pair in paired:
        review = pair.get("review_case") or {}
        if str(review.get("category") or "") != "new_source" and str(
            review.get("corpus_scope") or ""
        ) != "new_external_source":
            continue
        candidate = pair.get("candidate") or {}
        modes = candidate.get("modes") or {}
        hybrid = modes.get("hybrid") or {}
        cases.append(
            {
                "case_id": pair.get("case_id"),
                "expected_document_ids": candidate.get("expected_document_ids") or [],
                "expected_chunk_ids": candidate.get("expected_chunk_ids") or [],
                "faiss_recalled_top_10": bool((candidate.get("candidate_presence") or {}).get("faiss_top_10")),
                "bm25_recalled_top_10": bool((candidate.get("candidate_presence") or {}).get("bm25_top_10")),
                "hybrid_recalled_top_10": bool((candidate.get("candidate_presence") or {}).get("hybrid_top_10")),
                "hybrid_first_relevant_rank": hybrid.get("first_relevant_rank"),
                "failed_at_3": not bool(hybrid.get("hit_at_3")),
                "top_wrong_results": [
                    item for item in list(hybrid.get("results") or [])[:3] if not item.get("is_acceptable_chunk")
                ],
                "suggested_error_types": (pair.get("classification") or {}).get("suggested_error_types") or [],
                "annotation_issue_possible": any(
                    item.get("type") == "annotation_incomplete"
                    for item in (pair.get("classification") or {}).get("suggested_error_types") or []
                ),
                "chunk_granularity_issue_possible": bool(
                    not hybrid.get("hit_at_3") and hybrid.get("document_hit_at_3")
                ),
                "query_chunk_wording_gap_possible": bool(
                    not (candidate.get("candidate_presence") or {}).get("faiss_top_10")
                    or not (candidate.get("candidate_presence") or {}).get("bm25_top_10")
                ),
                "metadata_or_title_gap_possible": bool(
                    (candidate.get("candidate_presence") or {}).get("faiss_top_10")
                    and not (candidate.get("candidate_presence") or {}).get("bm25_top_10")
                ),
                "human_validated": False,
            }
        )
    return {
        "new_source_case_count": len(cases),
        "failed_at_3_count": sum(bool(case["failed_at_3"]) for case in cases),
        "cases": cases,
        "human_validated": False,
        "analysis_type": "rule_based_diagnostic",
    }


def build_negative_analysis(paired: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    positive_scores: list[float] = []
    negative_scores: list[float] = []
    positive_margins: list[float] = []
    negative_margins: list[float] = []
    for pair in paired:
        review = pair.get("review_case") or {}
        candidate = pair.get("candidate") or {}
        hybrid = ((candidate.get("modes") or {}).get("hybrid") or {})
        is_negative = str(review.get("category") or "") == "negative" or str(
            review.get("corpus_scope") or ""
        ) == "confusion_negative"
        score = hybrid.get("top_result_score")
        margin = hybrid.get("top1_top2_margin")
        if score is not None:
            (negative_scores if is_negative else positive_scores).append(float(score))
        if margin is not None:
            (negative_margins if is_negative else positive_margins).append(float(margin))
        if not is_negative:
            continue
        forbidden = {int(item) for item in candidate.get("must_not_return_document_ids") or []}
        top_results = list(hybrid.get("results") or [])[:10]
        false_positive = any(
            int(item.get("document_id") or -1) in forbidden for item in top_results[:3]
        )
        top = top_results[0] if top_results else {}
        cases.append(
            {
                "case_id": pair.get("case_id"),
                "false_positive_at_3": false_positive,
                "top_10": top_results,
                "top1_score": score,
                "top1_top2_margin": margin,
                "faiss_bm25_agree_top1": bool(
                    top
                    and top.get("faiss_rank") == 1
                    and top.get("bm25_rank") == 1
                ),
                "suggested_confusion_types": [
                    item.get("type")
                    for item in (pair.get("classification") or {}).get("suggested_error_types") or []
                ],
                "human_validated": False,
            }
        )

    def distribution(values: list[float]) -> dict[str, Any]:
        return {
            "count": len(values),
            "min": round(min(values), 6) if values else None,
            "max": round(max(values), 6) if values else None,
            "mean": round(mean(values), 6) if values else None,
            "median": round(float(np.median(values)), 6) if values else None,
        }

    overlap = False
    if positive_scores and negative_scores:
        overlap = max(min(positive_scores), min(negative_scores)) <= min(
            max(positive_scores), max(negative_scores)
        )
    return {
        "negative_case_count": len(cases),
        "false_positive_at_3_count": sum(bool(case["false_positive_at_3"]) for case in cases),
        "cases": cases,
        "score_distributions": {
            "positive_top1": distribution(positive_scores),
            "negative_top1": distribution(negative_scores),
            "positive_margin": distribution(positive_margins),
            "negative_margin": distribution(negative_margins),
            "top1_score_ranges_overlap": overlap,
            "production_threshold_determined": False,
        },
        "sample_limited": True,
        "human_validated": False,
    }


def error_type_counts(paired: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for pair in paired:
        for item in (pair.get("classification") or {}).get("suggested_error_types") or []:
            counter[str(item.get("type"))] += 1
    return dict(sorted(counter.items()))


def assess_reranker(paired: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [pair for pair in paired if (pair.get("classification") or {}).get("status") == "failed"]
    retrieval = 0
    ranking = 0
    hit10 = 0
    for pair in failures:
        types = {
            item.get("type")
            for item in (pair.get("classification") or {}).get("suggested_error_types") or []
        }
        retrieval += int("retrieval_failure" in types)
        ranking += int("ranking_failure" in types)
        hit10 += int(bool((((pair.get("candidate") or {}).get("modes") or {}).get("hybrid") or {}).get("hit_at_10")))
    recall10 = hit10 / len(failures) if failures else 1.0
    assessment = "inconclusive"
    evidence = [
        f"failed_cases={len(failures)}",
        f"ranking_failures={ranking}",
        f"retrieval_failures={retrieval}",
        f"failed_case_hybrid_hit_at_10_rate={round(recall10, 4)}",
        "holdout_human_validated=false",
        "sample_limited=true",
    ]
    if failures and ranking > retrieval and recall10 >= 0.8:
        evidence.append("ranking failures dominate, but human validation is still required")
    elif retrieval > ranking:
        evidence.append("candidate recall failures cannot be repaired by reranking alone")
    return {
        "assessment": assessment,
        "evidence": evidence,
        "reranker_implemented": False,
        "human_validated": False,
    }
