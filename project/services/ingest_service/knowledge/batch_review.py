from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .chunk_exporter import DEFAULT_RUNS_DIR
from .review import load_candidates_jsonl_with_warnings

DEFAULT_BATCH_SUMMARY_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_review_runs_summary.json"
DEFAULT_BATCH_SUMMARY_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_review_runs_summary.md"
REVIEW_SHEET_NAME = "sample_knowledge_unit_review_sheet.jsonl"


def _flags(record: dict[str, Any]) -> list[str]:
    flags = record.get("quality_flags")
    return flags if isinstance(flags, list) else []


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in counter.items()))


def _run_name_from_sheet(path: Path) -> str:
    return path.parent.name


def discover_review_sheets(runs_dir: str | Path = DEFAULT_RUNS_DIR, run_names: list[str] | None = None) -> list[Path]:
    root = Path(runs_dir)
    if run_names:
        return [root / name / REVIEW_SHEET_NAME for name in run_names]
    if not root.exists():
        return []
    return sorted(path for path in root.glob(f"*/{REVIEW_SHEET_NAME}") if path.is_file())


def summarize_review_records(records: list[dict], *, run_name: str = "") -> dict[str, Any]:
    items = [record for record in records or [] if isinstance(record, dict)]
    by_unit_type = Counter(record.get("unit_type") or "unknown" for record in items)
    by_recommended = Counter(record.get("recommended_review_status") or "unknown" for record in items)
    by_quality = Counter(record.get("quality_level") or "unknown" for record in items)
    by_flag = Counter(flag for record in items for flag in _flags(record))
    duplicate_count = sum(
        1
        for record in items
        if record.get("recommended_review_status") == "duplicate" or "duplicate_like" in _flags(record)
    )
    accepted_potential = sum(1 for record in items if record.get("recommended_review_status") == "accepted")
    needs_edit_potential = sum(1 for record in items if record.get("recommended_review_status") == "needs_edit")
    average_quality = sum(float(record.get("quality_score") or 0.0) for record in items) / len(items) if items else 0.0
    return {
        "run_name": run_name,
        "total_candidates": len(items),
        "counts_by_unit_type": _counter_dict(by_unit_type),
        "counts_by_recommended_review_status": _counter_dict(by_recommended),
        "counts_by_quality_level": _counter_dict(by_quality),
        "quality_flags": _counter_dict(by_flag),
        "duplicate_count": duplicate_count,
        "accepted_candidate_potential": accepted_potential,
        "needs_edit_candidate_potential": needs_edit_potential,
        "average_quality_score": round(average_quality, 3),
    }


def summarize_review_runs(
    *,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    run_names: list[str] | None = None,
) -> dict[str, Any]:
    sheets = discover_review_sheets(runs_dir, run_names)
    warnings: list[str] = []
    run_summaries: list[dict[str, Any]] = []
    all_records: list[dict] = []

    for sheet in sheets:
        records, sheet_warnings = load_candidates_jsonl_with_warnings(sheet)
        warnings.extend(f"{sheet}:{warning}" for warning in sheet_warnings)
        run_name = _run_name_from_sheet(sheet)
        summary = summarize_review_records(records, run_name=run_name)
        summary["review_sheet"] = str(sheet)
        run_summaries.append(summary)
        all_records.extend(records)

    if run_names:
        for name in run_names:
            sheet = Path(runs_dir) / name / REVIEW_SHEET_NAME
            if not sheet.exists():
                warnings.append(f"run_review_sheet_not_found:{sheet}")

    aggregate = summarize_review_records(all_records, run_name="aggregate")
    return {
        "status": "ok",
        "runs_dir": str(Path(runs_dir)),
        "run_count": len(run_summaries),
        "runs": run_summaries,
        "aggregate": aggregate,
        "warnings": warnings,
        "database_written": False,
    }


def write_batch_summary_json(summary: dict[str, Any], path: str | Path = DEFAULT_BATCH_SUMMARY_JSON) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def write_batch_summary_markdown(summary: dict[str, Any], path: str | Path = DEFAULT_BATCH_SUMMARY_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    aggregate = summary.get("aggregate") or {}
    lines = [
        "# Knowledge Unit Review Runs Summary",
        "",
        "## Summary",
        "",
        f"- run_count: {summary.get('run_count', 0)}",
        f"- total_candidates: {aggregate.get('total_candidates', 0)}",
        f"- counts_by_unit_type: {json.dumps(aggregate.get('counts_by_unit_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- counts_by_recommended_review_status: {json.dumps(aggregate.get('counts_by_recommended_review_status') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- counts_by_quality_level: {json.dumps(aggregate.get('counts_by_quality_level') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- duplicate_count: {aggregate.get('duplicate_count', 0)}",
        f"- accepted_candidate_potential: {aggregate.get('accepted_candidate_potential', 0)}",
        f"- needs_edit_candidate_potential: {aggregate.get('needs_edit_candidate_potential', 0)}",
        f"- average_quality_score: {float(aggregate.get('average_quality_score') or 0.0):.3f}",
        f"- database_written: false",
        "",
        "## Quality Flags",
        "",
        f"- quality_flags: {json.dumps(aggregate.get('quality_flags') or {}, ensure_ascii=False, sort_keys=True)}",
        "",
        "## Runs",
        "",
    ]
    runs = summary.get("runs") or []
    if not runs:
        lines.append("- none")
    else:
        for run in runs:
            lines.append(
                f"- {run.get('run_name')}: total={run.get('total_candidates', 0)}, "
                f"accepted_potential={run.get('accepted_candidate_potential', 0)}, "
                f"duplicates={run.get('duplicate_count', 0)}, sheet={run.get('review_sheet')}"
            )
    lines.extend(
        [
            "",
            "## Recommendations",
            "",
            "- Use per-run review sheets as human audit inputs; do not edit aggregate summaries as source data.",
            "- Prioritize runs with accepted_candidate_potential > 0 for manual review.",
            "- Keep database writes disabled until a later writer phase explicitly enables dry-run/write-db controls.",
        ]
    )
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        for warning in summary.get("warnings") or []:
            lines.append(f"- {warning}")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output
