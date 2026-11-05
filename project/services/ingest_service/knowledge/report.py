from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .contracts import KnowledgeUnitCandidate, VALID_UNIT_TYPES

DEFAULT_OUTPUT_DIR = Path("runtime") / "knowledge_unit_candidates"
DEFAULT_CANDIDATES_JSONL = DEFAULT_OUTPUT_DIR / "knowledge_unit_candidates.jsonl"
DEFAULT_REPORT_MD = DEFAULT_OUTPUT_DIR / "knowledge_unit_extraction_report.md"


def write_candidates_jsonl(candidates: Iterable[KnowledgeUnitCandidate], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for candidate in candidates:
            f.write(json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return output


def _duplicate_removed_count(candidates: list[KnowledgeUnitCandidate]) -> int:
    total = 0
    for candidate in candidates:
        try:
            total += max(0, int((candidate.source or {}).get("merged_source_count") or 1) - 1)
        except Exception:
            continue
    return total


def _missing_source_count(candidates: list[KnowledgeUnitCandidate]) -> int:
    count = 0
    for candidate in candidates:
        source = candidate.source or {}
        if not source.get("source_text_preview") or (source.get("document_id") is None and source.get("chunk_id") is None):
            count += 1
    return count


def write_extraction_report(candidates: Iterable[KnowledgeUnitCandidate], path: str | Path) -> Path:
    items = list(candidates or [])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    counts = Counter(c.unit_type for c in items)
    average_confidence = sum(float(c.confidence or 0.0) for c in items) / len(items) if items else 0.0
    warnings_count = sum(len(c.warnings or []) for c in items)
    duplicate_removed_count = _duplicate_removed_count(items)
    missing_source_count = _missing_source_count(items)

    grouped: dict[str, list[KnowledgeUnitCandidate]] = defaultdict(list)
    for candidate in items:
        grouped[candidate.unit_type].append(candidate)
    for unit_type in grouped:
        grouped[unit_type].sort(key=lambda c: float(c.confidence or 0.0), reverse=True)

    lines = [
        "# Knowledge Unit Extraction Dry-run Report",
        "",
        "## Summary",
        "",
        f"- total_candidates: {len(items)}",
        f"- counts_by_unit_type: {json.dumps({t: counts.get(t, 0) for t in sorted(VALID_UNIT_TYPES)}, ensure_ascii=False, sort_keys=True)}",
        f"- average_confidence: {average_confidence:.3f}",
        f"- warnings_count: {warnings_count}",
        f"- duplicate_removed_count: {duplicate_removed_count}",
        f"- missing_source_count: {missing_source_count}",
        "",
        "## Top Candidates By Type",
        "",
    ]

    for unit_type in sorted(VALID_UNIT_TYPES):
        lines.append(f"### {unit_type}")
        top = grouped.get(unit_type, [])[:5]
        if not top:
            lines.append("- none")
        for candidate in top:
            title = candidate.title or candidate.canonical_name or candidate.dedup_key
            lines.append(f"- {title} | confidence={float(candidate.confidence or 0.0):.2f} | dedup_key={candidate.dedup_key}")
        lines.append("")

    representative_warnings = []
    for candidate in items:
        for warning in candidate.warnings or []:
            representative_warnings.append(f"{candidate.dedup_key}: {warning}")
            if len(representative_warnings) >= 12:
                break
        if len(representative_warnings) >= 12:
            break

    lines.extend(
        [
            "## Representative Warnings",
            "",
            *(f"- {warning}" for warning in representative_warnings),
        ]
    )
    if not representative_warnings:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Recommendations",
            "",
            "- Review low-confidence and duplicate-merged candidates before any database writer phase.",
            "- Keep this phase as dry-run output only; do not upsert to knowledge_units until human review is added.",
            "- Use small document samples to inspect false positives before scaling extraction.",
        ]
    )

    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output
