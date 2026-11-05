from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .quality import VALID_REVIEW_STATUSES, score_candidate_quality


def _json_default(value: Any) -> str:
    return str(value)


def _source(candidate: dict[str, Any]) -> dict[str, Any]:
    source = candidate.get("source")
    return source if isinstance(source, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _stable_candidate_id(candidate: dict[str, Any]) -> str:
    existing = _text(candidate.get("candidate_id") or candidate.get("id"))
    if existing:
        return existing
    source = _source(candidate)
    payload = {
        "dedup_key": candidate.get("dedup_key"),
        "source": {
            "document_id": source.get("document_id"),
            "chunk_id": source.get("chunk_id"),
            "page_no": source.get("page_no"),
            "source_text_preview": source.get("source_text_preview"),
        },
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default).encode("utf-8")).hexdigest()
    return f"ku_{digest[:16]}"


def load_candidates_jsonl(path: str) -> list[dict]:
    records, _warnings = load_candidates_jsonl_with_warnings(path)
    return records


def load_candidates_jsonl_with_warnings(path: str | Path) -> tuple[list[dict], list[str]]:
    input_path = Path(path)
    if not input_path.exists():
        return [], [f"input_not_found:{input_path}"]
    records: list[dict] = []
    warnings: list[str] = []
    with input_path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception as exc:
                warnings.append(f"invalid_json_line:{line_no}:{type(exc).__name__}")
                continue
            if not isinstance(item, dict):
                warnings.append(f"non_object_line:{line_no}")
                continue
            records.append(item)
    return records, warnings


def build_review_records(candidates: list[dict]) -> list[dict]:
    records: list[dict] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        source = _source(candidate)
        quality = score_candidate_quality(candidate)
        review_status = _text(candidate.get("review_status")) if _text(candidate.get("review_status")) in VALID_REVIEW_STATUSES else "pending"
        records.append(
            {
                "candidate_id": _stable_candidate_id(candidate),
                "unit_type": _text(candidate.get("unit_type")),
                "canonical_name": _text(candidate.get("canonical_name")),
                "title": _text(candidate.get("title")),
                "content": _text(candidate.get("content")),
                "source_text_preview": _text(source.get("source_text_preview")),
                "dedup_key": _text(candidate.get("dedup_key")),
                "confidence": float(candidate.get("confidence") or 0.0),
                "quality_score": quality["quality_score"],
                "quality_level": quality["quality_level"],
                "quality_flags": list(quality["quality_flags"]),
                "recommended_review_status": quality["recommended_review_status"],
                "review_status": review_status,
                "reviewer_note": _text(candidate.get("reviewer_note")),
            }
        )
    return records


def write_review_sheet(records: list[dict], path: str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for record in records or []:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
    return output


def load_reviewed_candidates(path: str) -> list[dict]:
    records = load_candidates_jsonl(path)
    return build_review_records(records) if records and "quality_score" not in records[0] else records


def filter_candidates_by_review_status(records: list[dict], allowed_statuses: list[str]) -> list[dict]:
    allowed = {status.strip() for status in allowed_statuses or [] if status and status.strip()}
    if not allowed:
        return list(records or [])
    return [record for record in records or [] if record.get("review_status") in allowed]
