from __future__ import annotations

from typing import Any


def _metric(payload: dict[str, Any], key: str) -> float:
    try:
        return float(payload.get(key) or 0.0)
    except Exception:
        return 0.0


def _increase_ratio(old_value: float, new_value: float) -> float:
    if old_value <= 0:
        return 0.0 if new_value <= 0 else float("inf")
    return (new_value - old_value) / old_value


def evaluate_release_gate(
    old_evaluation: dict[str, Any],
    candidate_evaluation: dict[str, Any],
    validation: dict[str, Any],
    snapshot: dict[str, Any],
    contract_checks: dict[str, bool],
) -> dict[str, Any]:
    old = dict(old_evaluation.get("modes", {}).get("hybrid") or {})
    candidate = dict(candidate_evaluation.get("modes", {}).get("hybrid") or {})
    failed: list[str] = []
    warnings: list[str] = []

    database_count = int(validation.get("database_valid_chunk_count") or 0)
    integrity_conditions = {
        "candidate_validation_passed": bool(validation.get("passed")),
        "faiss_count_equals_database": int(validation.get("faiss_count") or 0) == database_count,
        "bm25_count_equals_database": int(validation.get("bm25_count") or 0) == database_count,
        "manifest_count_equals_database": int(validation.get("manifest_count") or 0) == database_count,
        "faiss_bm25_chunk_id_set_equal": bool(validation.get("faiss_bm25_chunk_id_set_equal")),
        "missing_chunk_ids_zero": not list(validation.get("missing_chunk_ids") or []),
        "duplicate_indexed_ids_zero": int(validation.get("duplicate_indexed_ids") or 0) == 0,
        "invalid_chunk_mapping_count_zero": int(validation.get("invalid_chunk_mapping_count") or 0) == 0,
        "provenance_accuracy_one": _metric(candidate, "provenance_accuracy") == 1.0,
        "candidate_reload_success": bool(validation.get("reload_success")),
        "old_snapshot_verified": bool(snapshot.get("snapshot_verified")),
        "rollback_available": bool(snapshot.get("rollback_available")),
    }

    old_recall = _metric(old, "old_query_recall_at_3")
    candidate_old_recall = _metric(candidate, "old_query_recall_at_3")
    quality_conditions = {
        "new_source_recall_at_3_gte_0_90": _metric(candidate, "new_source_recall_at_3") >= 0.90,
        "new_source_hit_rate_gte_0_90": _metric(candidate, "new_source_hit_rate") >= 0.90,
        "old_query_recall_drop_lte_0_05": old_recall - candidate_old_recall <= 0.05,
        "source_document_accuracy_at_3_gte_0_90": _metric(candidate, "source_document_accuracy_at_3") >= 0.90,
        "negative_false_positive_rate_lte_0_25": _metric(candidate, "negative_case_false_positive_rate") <= 0.25,
        "empty_result_rate_not_higher": _metric(candidate, "empty_result_rate") <= _metric(old, "empty_result_rate"),
        "mrr_not_significantly_lower": _metric(candidate, "mrr") >= _metric(old, "mrr") - 0.05,
        "precision_at_1_not_significantly_lower": _metric(candidate, "precision_at_1") >= _metric(old, "precision_at_1") - 0.10,
    }

    average_increase = _increase_ratio(
        _metric(old, "average_latency_ms"), _metric(candidate, "average_latency_ms")
    )
    p95_increase = _increase_ratio(
        _metric(old, "p95_latency_ms"), _metric(candidate, "p95_latency_ms")
    )
    performance_conditions = {
        "fresh_encoding_latency_evidence": not any(
            bool(payload.get("query_embeddings_supplied"))
            or (payload.get("embedding_provenance") or {}).get("kind") in {
                "recorded_real_model_query_vectors", "cached_embeddings",
            }
            for payload in (old_evaluation, candidate_evaluation)
        ),
        "average_latency_increase_lte_20_percent": average_increase <= 0.20,
        "p95_latency_increase_lte_30_percent": p95_increase <= 0.30,
    }
    required_contracts = {"sources_schema", "retrieval_count", "agent_answer", "quick_regression", "retrieval_smoke"}
    contract_conditions = {
        f"contract_{key}": bool(contract_checks.get(key))
        for key in sorted(required_contracts | set(contract_checks))
    }

    all_conditions = {
        **integrity_conditions,
        **quality_conditions,
        **performance_conditions,
        **contract_conditions,
    }
    failed.extend(key for key, passed in all_conditions.items() if not passed)
    if candidate_evaluation.get("sample_limited", True):
        warnings.append("holdout_sample_limited")
    passed = not failed
    return {
        "passed": passed,
        "activation_allowed": passed,
        "candidate_binding": {
            "version": validation.get("candidate_version"),
            "evaluation_version": candidate_evaluation.get("index_version"),
            "hashes": dict(validation.get("candidate_hashes") or {}),
        },
        "reason": "all_release_conditions_passed" if passed else "one_or_more_release_conditions_failed",
        "failed_conditions": failed,
        "warnings": warnings,
        "integrity_conditions": integrity_conditions,
        "quality_conditions": quality_conditions,
        "performance_conditions": performance_conditions,
        "contract_conditions": contract_conditions,
        "thresholds": {
            "new_source_recall_at_3": 0.90,
            "new_source_hit_rate": 0.90,
            "old_query_recall_drop": 0.05,
            "source_document_accuracy_at_3": 0.90,
            "negative_false_positive_rate": 0.25,
            "mrr_allowed_drop": 0.05,
            "precision_at_1_allowed_drop": 0.10,
            "average_latency_increase": 0.20,
            "p95_latency_increase": 0.30,
        },
        "observed": {
            "old_query_recall_drop": round(old_recall - candidate_old_recall, 4),
            "average_latency_increase_ratio": round(average_increase, 4),
            "p95_latency_increase_ratio": round(p95_increase, 4),
        },
    }
