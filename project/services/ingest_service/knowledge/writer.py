from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .provenance_backfill import DEFAULT_RUNS_DIR, backfill_candidates_provenance
from .write_gate import evaluate_write_gate
from .writer_mapping import map_candidates_to_write_plan

DEFAULT_ACCEPTED_INPUT = Path("runtime") / "knowledge_unit_candidates" / "batch_accepted_candidates_for_writer.jsonl"

TRANSACTION_STRATEGY = {
    "required": True,
    "scope": "single batch of accepted knowledge unit write plans",
    "steps": [
        "open transaction after explicit --write-db approval",
        "upsert knowledge_units main records first",
        "upsert extension-table records only after main-record success",
        "commit only after post-write verification succeeds",
    ],
}

ROLLBACK_STRATEGY = {
    "required": True,
    "triggers": [
        "any INSERT/UPDATE error",
        "affected-row mismatch",
        "post-write verification mismatch",
        "unexpected duplicate dedup_key conflict",
    ],
    "action": "rollback the full batch transaction and keep dry-run artifacts for audit",
}

POST_WRITE_VERIFICATION_STRATEGY = {
    "required": True,
    "checks": [
        "count written rows by dedup_key",
        "verify unit_type/canonical_name/content/source ids",
        "verify extension preview rows for formula/component/thermal_path/fault_case when enabled",
        "verify no blocked candidate was written",
    ],
}


def _is_accepted(record: dict[str, Any]) -> bool:
    return str(record.get("review_status") or "").strip() == "accepted"


def _load_jsonl(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"accepted candidate input not found: {input_path}")

    records: list[dict[str, Any]] = []
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


def load_accepted_candidates(path: str) -> list[dict]:
    records, _warnings = _load_jsonl(path)
    return [record for record in records if _is_accepted(record)]


def build_writer_dry_run(candidates: list[dict]) -> dict:
    input_records = [record for record in candidates or [] if isinstance(record, dict)]
    accepted = [record for record in input_records if _is_accepted(record)]
    skipped = len(input_records) - len(accepted)

    result = map_candidates_to_write_plan(accepted)
    result.update(
        {
            "status": "ok",
            "total_input_records": len(input_records),
            "total_candidates": len(accepted),
            "non_accepted_skipped_count": skipped,
            "database_written": False,
            "db_connection_opened": False,
            "write_mode": "dry_run",
        }
    )
    result["can_enter_phase2b"] = int(result.get("blocked_count") or 0) == 0
    return result


def build_writer_dry_run_from_path(path: str | Path = DEFAULT_ACCEPTED_INPUT) -> dict:
    records, loader_warnings = _load_jsonl(path)
    result = build_writer_dry_run(records)
    result["input_path"] = str(Path(path))
    result["loader_warnings"] = loader_warnings
    return result


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in counter.items()))


def _issue_counts(plans: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for plan in plans:
        for item in plan.get(field) or []:
            if isinstance(item, dict):
                counter[str(item.get("type") or "unknown")] += 1
    return _counter_dict(counter)


def build_writer_gate_dry_run(
    candidates: list[dict],
    *,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    allow_missing_provenance: bool = False,
) -> dict:
    input_records = [record for record in candidates or [] if isinstance(record, dict)]
    accepted = [record for record in input_records if _is_accepted(record)]
    skipped = len(input_records) - len(accepted)

    provenance_result = backfill_candidates_provenance(accepted, str(runs_dir))
    result = map_candidates_to_write_plan(provenance_result.get("candidates") or [])
    plans = list(result.get("write_plans") or [])

    for plan in plans:
        gate = evaluate_write_gate(plan, allow_missing_provenance=allow_missing_provenance)
        plan["write_gate"] = gate
        plan["gate_can_write"] = bool(gate.get("can_write"))
        plan["gate_blocking_errors"] = gate.get("blocking_errors") or []
        plan["gate_warnings"] = gate.get("warnings") or []

    gate_ready_count = sum(1 for plan in plans if plan.get("gate_can_write"))
    gate_blocked_count = len(plans) - gate_ready_count

    result.update(
        {
            "status": "ok",
            "total_input_records": len(input_records),
            "total_candidates": len(accepted),
            "non_accepted_skipped_count": skipped,
            "provenance_ready_count": provenance_result.get("provenance_ready_count", 0),
            "provenance_partial_count": provenance_result.get("provenance_partial_count", 0),
            "provenance_missing_count": provenance_result.get("provenance_missing_count", 0),
            "provenance_warnings_by_type": provenance_result.get("warnings_by_type") or {},
            "provenance_index_summary": provenance_result.get("index_summary") or {},
            "gate_ready_count": gate_ready_count,
            "gate_blocked_count": gate_blocked_count,
            "blocking_errors_by_type": _issue_counts(plans, "gate_blocking_errors"),
            "warnings_by_type": _issue_counts(plans, "gate_warnings"),
            "allow_missing_provenance": bool(allow_missing_provenance),
            "allow_missing_provenance_default": False,
            "write_db_required": True,
            "transaction_strategy": TRANSACTION_STRATEGY,
            "rollback_strategy": ROLLBACK_STRATEGY,
            "post_write_verification_strategy": POST_WRITE_VERIFICATION_STRATEGY,
            "can_enter_phase2b_write": gate_blocked_count == 0,
            "database_written": False,
            "db_connection_opened": False,
            "write_mode": "write_gate_dry_run",
        }
    )
    return result


def build_writer_gate_dry_run_from_path(
    path: str | Path = DEFAULT_ACCEPTED_INPUT,
    *,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    allow_missing_provenance: bool = False,
) -> dict:
    records, loader_warnings = _load_jsonl(path)
    result = build_writer_gate_dry_run(
        records,
        runs_dir=runs_dir,
        allow_missing_provenance=allow_missing_provenance,
    )
    result["input_path"] = str(Path(path))
    result["runs_dir"] = str(Path(runs_dir))
    result["loader_warnings"] = loader_warnings
    return result
