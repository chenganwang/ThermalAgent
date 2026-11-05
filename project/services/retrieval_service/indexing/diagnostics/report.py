from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import json
import os


def _atomic_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def _write_json(path: Path, payload: Any) -> Path:
    return _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    return _atomic_text(
        path,
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows),
    )


def _analysis_markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", "", "- human_validated: false", "- analysis_type: rule_based_diagnostic", ""]
    for key, value in payload.items():
        if key == "cases" or isinstance(value, (dict, list)):
            continue
        lines.append(f"- {key}: {value}")
    for case in payload.get("cases") or []:
        lines.extend(["", f"## {case.get('case_id')}", ""])
        for key, value in case.items():
            if key in {"case_id", "top_10", "top_wrong_results", "displacing_chunks"}:
                continue
            lines.append(f"- {key}: {value}")
        evidence = case.get("displacing_chunks") or case.get("top_wrong_results") or case.get("top_10") or []
        if evidence:
            lines.append("- evidence:")
            for item in evidence[:10]:
                lines.append(
                    f"  - rank={item.get('rank')} chunk={item.get('chunk_id')} "
                    f"doc={item.get('document_id')} source={item.get('source_name')} "
                    f"faiss_rank={item.get('faiss_rank')} bm25_rank={item.get('bm25_rank')}"
                )
    return "\n".join(lines) + "\n"


def _summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    boundaries = dict(payload.get("boundaries") or {})
    paired = list(payload.get("paired") or [])
    classification_counts = dict(payload.get("error_type_counts") or {})
    failed = sum(
        (item.get("classification") or {}).get("status") == "failed" for item in paired
    )
    return {
        "execution_summary": {
            "per_query_count": len(paired),
            "failed_or_flagged_count": failed,
            "old_and_candidate_evaluated": True,
            "modes": ["faiss", "bm25", "hybrid"],
            "top_k": 10,
        },
        "environment": payload.get("environment") or {},
        "metrics": payload.get("metrics") or {},
        "error_type_counts": classification_counts,
        "old_query_analysis_summary": {
            key: value
            for key, value in (payload.get("old_query_analysis") or {}).items()
            if key != "cases"
        },
        "new_source_analysis_summary": {
            key: value
            for key, value in (payload.get("new_source_analysis") or {}).items()
            if key != "cases"
        },
        "negative_analysis_summary": {
            key: value
            for key, value in (payload.get("negative_analysis") or {}).items()
            if key not in {"cases", "score_distributions"}
        },
        "chunk_audit_summary": {
            key: value
            for key, value in (payload.get("chunk_audit") or {}).items()
            if key not in {"candidates", "chunk_flags", "duplicate_groups", "near_duplicate_candidates"}
        },
        "reranker_assessment": payload.get("reranker_assessment") or {},
        "verified_facts": boundaries,
        "heuristic_suggestions": {
            "error_taxonomy": classification_counts,
            "chunk_noise_candidates_are_human_unconfirmed": True,
        },
        "pending_human_validation": True,
        "human_validated": False,
        "sample_limited": True,
    }


def _summary_markdown(summary: dict[str, Any]) -> str:
    execution = summary.get("execution_summary") or {}
    lines = [
        "# Retrieval Diagnostics Summary",
        "",
        "## Execution Summary",
        "",
        f"- per-query diagnostics: {execution.get('per_query_count')}",
        f"- modes: {', '.join(execution.get('modes') or [])}",
        f"- top-k: {execution.get('top_k')}",
        "- candidate activated: false",
        "- database written: false",
        "- production retrieval changed: false",
        "",
        "## Metrics",
        "",
        "| Configuration | R@1 | R@3 | R@5 | R@10 | P@1 | P@3 | MRR | Doc R@3 | Avg ms | P95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in (summary.get("metrics") or {}).items():
        strict = metrics.get("strict_expected") or {}
        acceptable = metrics.get("acceptable") or {}
        document = metrics.get("document") or {}
        lines.append(
            f"| {name} | {strict.get('recall_at_1')} | {strict.get('recall_at_3')} | "
            f"{strict.get('recall_at_5')} | {strict.get('recall_at_10')} | "
            f"{acceptable.get('precision_at_1')} | {acceptable.get('precision_at_3')} | "
            f"{acceptable.get('mrr')} | {document.get('recall_at_3')} | "
            f"{metrics.get('average_latency_ms')} | {metrics.get('p95_latency_ms')} |"
        )
    lines.extend(["", "## Heuristic Suggestions", ""])
    for key, value in (summary.get("error_type_counts") or {}).items():
        lines.append(f"- {key}: {value}")
    reranker = summary.get("reranker_assessment") or {}
    lines.extend(
        [
            "",
            "## Reranker Assessment",
            "",
            f"- assessment: {reranker.get('assessment')}",
        ]
    )
    lines.extend(f"- evidence: {item}" for item in reranker.get("evidence") or [])
    lines.extend(
        [
            "",
            "## Verified Facts",
            "",
        ]
    )
    for key, value in (summary.get("verified_facts") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Pending Human Validation",
            "",
            "- Holdout annotations remain human_validated=false.",
            "- Suggested error types and chunk-noise flags are deterministic heuristics, not human conclusions.",
            "- The sample is limited and cannot set a production rejection threshold.",
        ]
    )
    return "\n".join(lines) + "\n"


def _per_query_markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["# Per-Query Retrieval Diagnostics", "", "All classifications are rule suggestions; human_reviewed=false."]
    for row in rows:
        classification = row.get("classification") or {}
        lines.extend(
            [
                "",
                f"## {row.get('case_id')}",
                "",
                f"- status: {classification.get('status')}",
                f"- suggested errors: {[item.get('type') for item in classification.get('suggested_error_types') or []]}",
                f"- old hybrid rank: {((row.get('rank_changes') or {}).get('hybrid') or {}).get('old_rank')}",
                f"- candidate hybrid rank: {((row.get('rank_changes') or {}).get('hybrid') or {}).get('candidate_rank')}",
                "- human reviewed: false",
            ]
        )
    return "\n".join(lines) + "\n"


def _write_error_matrix(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "case_id",
                "status",
                "suggested_error_types",
                "old_hybrid_rank",
                "candidate_hybrid_rank",
                "human_reviewed",
            ),
        )
        writer.writeheader()
        for row in rows:
            classification = row.get("classification") or {}
            rank = (row.get("rank_changes") or {}).get("hybrid") or {}
            writer.writerow(
                {
                    "case_id": row.get("case_id"),
                    "status": classification.get("status"),
                    "suggested_error_types": "|".join(
                        str(item.get("type"))
                        for item in classification.get("suggested_error_types") or []
                    ),
                    "old_hybrid_rank": rank.get("old_rank"),
                    "candidate_hybrid_rank": rank.get("candidate_rank"),
                    "human_reviewed": False,
                }
            )
    os.replace(temporary, path)
    return path


def write_diagnostics_reports(output_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary_payload(payload)
    paired = list(payload.get("paired") or [])
    old_analysis = dict(payload.get("old_query_analysis") or {})
    new_analysis = dict(payload.get("new_source_analysis") or {})
    negative_analysis = dict(payload.get("negative_analysis") or {})
    chunk_audit = dict(payload.get("chunk_audit") or {})
    paths = {
        "summary_json": _write_json(output_dir / "retrieval_diagnostics_summary.json", summary),
        "summary_markdown": _atomic_text(output_dir / "retrieval_diagnostics_summary.md", _summary_markdown(summary)),
        "per_query_jsonl": _write_jsonl(output_dir / "per_query_diagnostics.jsonl", paired),
        "per_query_markdown": _atomic_text(output_dir / "per_query_diagnostics.md", _per_query_markdown(paired)),
        "error_matrix_csv": _write_error_matrix(output_dir / "retrieval_error_matrix.csv", paired),
        "old_query_json": _write_json(output_dir / "old_query_regression_analysis.json", old_analysis),
        "old_query_markdown": _atomic_text(output_dir / "old_query_regression_analysis.md", _analysis_markdown("Old Query Regression Analysis", old_analysis)),
        "new_source_json": _write_json(output_dir / "new_source_recall_analysis.json", new_analysis),
        "new_source_markdown": _atomic_text(output_dir / "new_source_recall_analysis.md", _analysis_markdown("New Source Recall Analysis", new_analysis)),
        "negative_json": _write_json(output_dir / "negative_case_analysis.json", negative_analysis),
        "negative_markdown": _atomic_text(output_dir / "negative_case_analysis.md", _analysis_markdown("Negative Case Analysis", negative_analysis)),
        "score_distribution_json": _write_json(output_dir / "score_distribution_analysis.json", negative_analysis.get("score_distributions") or {}),
        "chunk_audit_json": _write_json(output_dir / "chunk_quality_audit.json", {key: value for key, value in chunk_audit.items() if key != "candidates"}),
        "chunk_audit_markdown": _atomic_text(output_dir / "chunk_quality_audit.md", _analysis_markdown("Chunk Quality Audit", {key: value for key, value in chunk_audit.items() if key != "candidates"})),
        "chunk_candidates_jsonl": _write_jsonl(output_dir / "chunk_quality_candidates.jsonl", list(chunk_audit.get("candidates") or [])),
    }
    return {key: str(path.resolve()) for key, path in paths.items()}
