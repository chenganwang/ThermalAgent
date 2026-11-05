from __future__ import annotations

from typing import Any

from .analyzer import (
    assess_reranker,
    build_negative_analysis,
    build_new_source_analysis,
    build_old_query_regression_analysis,
    compute_configuration_metrics,
    error_type_counts,
    pair_bundle_diagnostics,
)


def run_diagnostics_pipeline(
    *,
    review_dataset: dict[str, Any],
    old_runtime,
    candidate_runtime,
    chunk_audit: dict[str, Any],
    environment: dict[str, Any],
    top_k: int = 10,
) -> dict[str, Any]:
    cases = [dict(item) for item in review_dataset.get("cases") or []]
    old_diagnostics = [old_runtime.diagnose_case(case, top_k=top_k) for case in cases]
    candidate_diagnostics = [
        candidate_runtime.diagnose_case(case, top_k=top_k) for case in cases
    ]
    flags = {
        int(key): list(value)
        for key, value in (chunk_audit.get("chunk_flags") or {}).items()
    }
    for diagnostic in old_diagnostics + candidate_diagnostics:
        for mode in (diagnostic.get("modes") or {}).values():
            for result in mode.get("results") or []:
                result["heuristic_noise_flags"] = list(
                    flags.get(int(result.get("chunk_id") or -1), [])
                )
    paired = pair_bundle_diagnostics(cases, old_diagnostics, candidate_diagnostics)
    metrics = {}
    for prefix, diagnostics in (("old", old_diagnostics), ("candidate", candidate_diagnostics)):
        for mode in ("faiss", "bm25", "hybrid"):
            metrics[f"{prefix}_{mode}"] = compute_configuration_metrics(
                diagnostics, mode_name=mode
            )
    return {
        "environment": {
            **environment,
            "top_k": top_k,
            "deterministic_seed": 0,
            "human_validated": False,
            "expected_only_metrics": True,
            "sample_limited": True,
        },
        "review_metadata": dict(review_dataset.get("metadata") or {}),
        "old_diagnostics": old_diagnostics,
        "candidate_diagnostics": candidate_diagnostics,
        "paired": paired,
        "metrics": metrics,
        "error_type_counts": error_type_counts(paired),
        "old_query_analysis": build_old_query_regression_analysis(
            paired, chunk_flags=flags
        ),
        "new_source_analysis": build_new_source_analysis(paired),
        "negative_analysis": build_negative_analysis(paired),
        "chunk_audit": chunk_audit,
        "reranker_assessment": assess_reranker(paired),
        "boundaries": {
            "production_index_modified": False,
            "candidate_activated": False,
            "active_pointer_modified": False,
            "database_written": False,
            "database_schema_modified": False,
            "embedding_modified": False,
            "retrieval_weights_modified": False,
            "retrieval_algorithm_modified": False,
            "reranker_implemented": False,
            "knowledge_units_production_fusion": False,
            "human_validation_faked": False,
        },
    }
