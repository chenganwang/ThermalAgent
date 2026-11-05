from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _issue(candidate_id: str, issue_type: str, message: str) -> dict[str, str]:
    return {"candidate_id": candidate_id, "type": issue_type, "message": message}


def _metadata(plan: dict[str, Any]) -> dict[str, Any]:
    value = plan.get("metadata_preview")
    return value if isinstance(value, dict) else {}


def _existing_issues(plan: dict[str, Any], field: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for item in plan.get(field) or []:
        if isinstance(item, dict):
            issues.append(
                {
                    "candidate_id": _text(item.get("candidate_id") or plan.get("candidate_id")),
                    "type": _text(item.get("type")) or "unknown",
                    "message": _text(item.get("message")),
                }
            )
    return issues


def evaluate_write_gate(write_plan: dict, allow_missing_provenance: bool = False) -> dict:
    plan = dict(write_plan or {}) if isinstance(write_plan, dict) else {}
    metadata = _metadata(plan)
    candidate_id = _text(plan.get("candidate_id")) or _text(metadata.get("candidate_id")) or "unknown_candidate"
    blocking_errors = _existing_issues(plan, "blocking_errors")
    warnings = _existing_issues(plan, "warnings")

    dedup_key = _text(plan.get("dedup_key") or metadata.get("dedup_key"))
    unit_type = _text(plan.get("unit_type"))
    canonical_name = _text(plan.get("canonical_name"))
    content = _text(plan.get("content"))
    review_status = _text(plan.get("review_status") or metadata.get("review_status"))
    provenance_status = _text(plan.get("provenance_status") or metadata.get("provenance_status")) or "missing"

    if not dedup_key:
        blocking_errors.append(_issue(candidate_id, "missing_dedup_key", "dedup_key is required before any write."))
    if not unit_type:
        blocking_errors.append(_issue(candidate_id, "missing_unit_type", "unit_type is required before any write."))
    if not canonical_name:
        blocking_errors.append(_issue(candidate_id, "missing_canonical_name", "canonical_name is required before any write."))
    if not content:
        blocking_errors.append(_issue(candidate_id, "missing_content", "content is required before any write."))
    if review_status != "accepted":
        blocking_errors.append(_issue(candidate_id, "review_status_not_accepted", "only accepted review records can pass the write gate."))

    if provenance_status == "missing":
        if allow_missing_provenance:
            warnings.append(
                _issue(
                    candidate_id,
                    "missing_provenance_allowed",
                    "provenance_status=missing is allowed only because allow_missing_provenance was set for dry-run evaluation.",
                )
            )
        else:
            blocking_errors.append(
                _issue(
                    candidate_id,
                    "missing_provenance",
                    "provenance_status=missing blocks future database writes unless allow_missing_provenance is explicitly approved.",
                )
            )
    elif provenance_status == "partial":
        warnings.append(
            _issue(
                candidate_id,
                "partial_provenance",
                "provenance_status=partial should be reviewed before future write-db execution.",
            )
        )
    elif provenance_status != "ready":
        warnings.append(
            _issue(candidate_id, "unknown_provenance_status", f"unrecognized provenance_status: {provenance_status}")
        )

    if not _present(plan.get("document_id")):
        warnings.append(_issue(candidate_id, "missing_document_id_for_gate", "document_id is still absent after provenance backfill."))
    if not _present(plan.get("source_chunk_id")):
        warnings.append(
            _issue(candidate_id, "missing_source_chunk_id_for_gate", "source_chunk_id is still absent after provenance backfill.")
        )

    warnings.append(
        _issue(
            candidate_id,
            "write_db_flag_required",
            "dry-run evaluation only; future real writes require an explicit --write-db flag.",
        )
    )

    return {
        "can_write": not blocking_errors,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "requires_write_db_flag": True,
        "requires_transaction": True,
        "requires_post_write_verification": True,
    }
