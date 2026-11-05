from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


ELIGIBLE_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".json",
    ".jsonl",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
}

THERMAL_RELEVANCE_TERMS = {
    "ashrae",
    "cdu",
    "chip",
    "cold plate",
    "coolant",
    "cooling",
    "data center",
    "datacenter",
    "facility water",
    "flow rate",
    "gpu",
    "heat",
    "high power",
    "liquid",
    "ocp",
    "pressure drop",
    "server",
    "thermal",
    "water cooled",
    "water-cooled",
}

LIQUID_COOLING_TERMS = {
    "cdu",
    "cold plate",
    "coolant",
    "ethylene glycol",
    "facility water",
    "flow",
    "glycol",
    "liquid",
    "pgw",
    "pressure drop",
    "propylene glycol",
    "water cooled",
    "water-cooled",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower_blob(path: Path) -> str:
    return f"{path.name} {path.stem} {path.parent.name}".lower().replace("_", " ").replace("-", " ")


def _matched_terms(path: Path, terms: set[str]) -> list[str]:
    blob = _lower_blob(path)
    return sorted(term for term in terms if term in blob)


def _file_entry(path: Path, root: Path) -> dict[str, Any]:
    thermal_terms = _matched_terms(path, THERMAL_RELEVANCE_TERMS)
    liquid_terms = _matched_terms(path, LIQUID_COOLING_TERMS)
    try:
        stat = path.stat()
        size = int(stat.st_size)
        modified = stat.st_mtime
    except OSError:
        size = 0
        modified = None
    return {
        "path": str(path),
        "relative_path": str(path.relative_to(root)) if path.is_relative_to(root) else path.name,
        "name": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": size,
        "modified_timestamp": modified,
        "thermal_relevance_terms": thermal_terms,
        "liquid_cooling_relevance_terms": liquid_terms,
        "thermal_relevance_score": len(thermal_terms),
        "liquid_cooling_relevance_score": len(liquid_terms),
    }


def _judgement(eligible_count: int, term_hits: int) -> str:
    if eligible_count <= 0:
        return "none"
    if term_hits >= 8 or eligible_count >= 5:
        return "high"
    if term_hits >= 3 or eligible_count >= 2:
        return "medium"
    return "low"


def _scan_root(root: Path, *, max_files: int) -> tuple[list[Path], bool]:
    if not root.exists():
        return [], False
    files: list[Path] = []
    truncated = False
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: str(item).lower()):
        files.append(path)
        if len(files) >= max_files:
            truncated = True
            break
    return files, truncated


def build_source_intake_report(
    *,
    primary_path: str | Path,
    fallback_path: str | Path,
    max_files: int = 5000,
) -> dict[str, Any]:
    """Build a file-list intake report without OCR, parsing, ingest, or API calls."""

    primary = Path(primary_path)
    fallback = Path(fallback_path)
    selected = primary if primary.exists() else fallback
    files, truncated = _scan_root(selected, max_files=max_files)

    suggested: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    block_reasons: Counter[str] = Counter()
    file_types: Counter[str] = Counter()
    thermal_hits = 0
    liquid_hits = 0

    for path in files:
        entry = _file_entry(path, selected)
        ext = entry["extension"] or "<none>"
        file_types[ext] += 1
        thermal_hits += int(entry.get("thermal_relevance_score") or 0)
        liquid_hits += int(entry.get("liquid_cooling_relevance_score") or 0)

        if ext not in ELIGIBLE_EXTENSIONS:
            item = dict(entry)
            item["block_reason"] = "unsupported_file_type"
            blocked.append(item)
            block_reasons["unsupported_file_type"] += 1
            continue
        if not entry["thermal_relevance_terms"] and not entry["liquid_cooling_relevance_terms"]:
            item = dict(entry)
            item["block_reason"] = "low_filename_topic_relevance"
            blocked.append(item)
            block_reasons["low_filename_topic_relevance"] += 1
            continue
        suggested.append(entry)

    return {
        "status": "ok" if selected.exists() else "source_path_missing",
        "scanned_paths": [
            {"path": str(primary), "exists": primary.exists(), "selected": primary == selected},
            {"path": str(fallback), "exists": fallback.exists(), "selected": fallback == selected and not primary.exists()},
        ],
        "selected_scan_root": str(selected),
        "scan_truncated": truncated,
        "max_files": int(max_files),
        "discovered_file_count": len(files),
        "eligible_file_count": len(suggested),
        "skipped_file_count": len(blocked),
        "file_type_distribution": dict(sorted(file_types.items())),
        "thermal_relevance_judgement": _judgement(len(suggested), thermal_hits),
        "liquid_cooling_relevance_judgement": _judgement(len(suggested), liquid_hits),
        "suggested_source_files": suggested[:80],
        "blocked_source_files": blocked[:80],
        "block_reasons": dict(sorted(block_reasons.items())),
        "needs_existing_chunk_ingestion": bool(suggested),
        "pdf_ingestion_executed": False,
        "ocr_executed": False,
        "external_api_called": False,
        "database_written": False,
    }


__all__ = [
    "ELIGIBLE_EXTENSIONS",
    "LIQUID_COOLING_TERMS",
    "THERMAL_RELEVANCE_TERMS",
    "build_source_intake_report",
]
