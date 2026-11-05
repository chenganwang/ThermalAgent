from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .review_validator import validate_review_record

DEFAULT_ACCEPTED_EXPORT_PATH = Path("runtime") / "knowledge_unit_candidates" / "accepted_candidates_for_writer.jsonl"


def _json_default(value: Any) -> str:
    return str(value)


def _is_accepted(record: dict[str, Any]) -> bool:
    return str(record.get("review_status") or "").strip() == "accepted"


def export_accepted_candidates(records: list[dict], output_path: str | Path = DEFAULT_ACCEPTED_EXPORT_PATH) -> dict:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    accepted_count = 0
    exported: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    for record in records or []:
        if not isinstance(record, dict) or not _is_accepted(record):
            continue
        accepted_count += 1
        validation = validate_review_record(record)
        warnings.extend(validation.get("warnings") or [])
        record_errors = list(validation.get("errors") or [])
        if record_errors:
            errors.extend(record_errors)
            blocked.append(
                {
                    "candidate_id": validation.get("candidate_id"),
                    "unit_type": record.get("unit_type"),
                    "canonical_name": record.get("canonical_name"),
                    "errors": record_errors,
                }
            )
            continue

        item = dict(record)
        item["writer_export_status"] = "accepted"
        item["database_written"] = False
        exported.append(item)

    with output.open("w", encoding="utf-8") as f:
        for item in exported:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")

    return {
        "output_path": str(output),
        "accepted_count": accepted_count,
        "exported_count": len(exported),
        "blocked_count": len(blocked),
        "blocked_accepted": blocked,
        "errors": errors,
        "warnings": warnings,
        "database_written": False,
    }
