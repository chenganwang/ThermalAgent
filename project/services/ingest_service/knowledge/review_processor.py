from __future__ import annotations

from collections import Counter
import re
from pathlib import Path
from typing import Any

from .phase2g_report import (
    DEFAULT_BATCH_ACCEPTED_INPUT,
    DEFAULT_REVIEW_SHORTLIST,
    DEFAULT_REVIEW_SHEET,
    RUNS_DIR,
    RUNTIME_DIR,
    TARGET_ACCEPTED_COUNT,
    load_jsonl_records,
)
from .provenance_backfill import backfill_candidates_provenance
from .contracts import VALID_UNIT_TYPES
from .review_validator import SEVERE_ACCEPTED_FLAGS, validate_review_record


AUTO_REVIEW_METHOD = "auto_strict_rule_based"
MIN_WRITE_THRESHOLD = 20

REVIEW_DISCOVERY_NAMES = (
    "phase2g_review_shortlist.jsonl",
    "phase2g_review_sheet.md",
    "phase2g_candidate_expansion_report.json",
    "phase2g_candidate_expansion_report.md",
    "phase2g_no_write_decision.json",
    "phase2g_no_write_decision.md",
    "knowledge_unit_phase2g_inventory_report.json",
    "knowledge_unit_phase2g_inventory_report.md",
)

PROMOTE_ACTIONS = {"can_promote_if_human_confirms"}
REJECT_ACTIONS = {"reject", "reject_suggested"}

FRAGMENT_START_RE = re.compile(r"^(?:and|or|but|however|while|considering|for example|generally|those)\b", re.I)
TRAILING_FRAGMENT_RE = re.compile(r"\b(?:for example|generally|however|while|and|or|i\.e)\s*$", re.I)
OCR_GARBAGE_RE = re.compile(r"(?:�|鍊\?|琛|颅|鈥|掳|脳)")
NUMERIC_OR_UNIT_RE = re.compile(r"\d|%|\b(?:lpm|l/min|kw|w/mk|w/\(?m\*?k\)?|c/w|psi|kpa|mpa|bar|degc|c)\b", re.I)
FAULT_RE = re.compile(r"leak|leakage|fault|failure|contamination|debris|block|risk|abnormal", re.I)
CONCEPT_MARKER_RE = re.compile(r"\b(?:is|are|means|refers|represents|defines|acts as|used to|affects|requires)\b", re.I)
COMPONENT_TERMS = {
    "cdu",
    "cold_plate",
    "connector",
    "coolant",
    "gpu",
    "hose",
    "manifold",
    "pump",
    "rpu",
    "tim",
}
PARAMETER_TERMS = {
    "density",
    "facility_water_temperature",
    "flow_rate",
    "pgw_concentration",
    "pressure_drop",
    "specific_heat",
    "thermal_conductivity",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _norm(value: Any) -> str:
    text = _text(value).lower().replace("-", "_").replace("/", "_")
    text = re.sub(r"[^0-9a-zA-Z_]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _status(record: dict[str, Any]) -> str:
    return _text(record.get("review_status") or record.get("current_review_status"))


def _dedup_key(record: dict[str, Any]) -> str:
    return _text(record.get("dedup_key"))


def _candidate_id(record: dict[str, Any]) -> str:
    return _text(record.get("candidate_id") or record.get("id") or record.get("dedup_key"))


def _quality_flags(record: dict[str, Any]) -> list[str]:
    flags = record.get("quality_flags")
    return [_text(flag) for flag in flags if _text(flag)] if isinstance(flags, list) else []


def _source_preview(record: dict[str, Any]) -> str:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return _text(record.get("source_text_preview") or source.get("source_text_preview"))


def _make_unit_code(record: dict[str, Any]) -> str:
    existing = _text(record.get("unit_code"))
    if existing:
        return existing
    base = _norm(_dedup_key(record))
    return base[:128] if base else _norm(_candidate_id(record))[:128]


def _normalized_content(content: Any) -> str:
    return re.sub(r"\s+", " ", _text(content)).strip()


def _normalize_review_record(record: dict[str, Any]) -> dict[str, Any]:
    item = dict(record)
    canonical = _norm(item.get("canonical_name") or item.get("title"))
    if canonical:
        item["canonical_name"] = canonical
        item.setdefault("title", canonical.replace("_", " "))
    item["content"] = _normalized_content(item.get("content"))
    if not _dedup_key(item) and item.get("unit_type") and canonical:
        item["dedup_key"] = f"{item['unit_type']}:{canonical}"
    item["unit_code"] = _make_unit_code(item)
    return item


def discover_phase2g_review_package(
    *,
    base_dir: str | Path = RUNTIME_DIR,
    current_accepted_pack: str | Path = DEFAULT_BATCH_ACCEPTED_INPUT,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
) -> dict[str, Any]:
    base = Path(base_dir)
    discovered = [base / name for name in REVIEW_DISCOVERY_NAMES if (base / name).exists()]
    selected = Path(DEFAULT_REVIEW_SHORTLIST)
    if not selected.exists():
        candidates = [path for path in discovered if "review" in path.name.lower() and path.suffix.lower() == ".jsonl"]
        selected = candidates[0] if candidates else selected

    records, warnings = load_jsonl_records(selected)
    accepted_records, accepted_warnings = load_jsonl_records(current_accepted_pack)
    warnings.extend(accepted_warnings)
    needs_edit = [record for record in records if _status(record) == "needs_edit"]
    existing_accepted = [record for record in accepted_records if _status(record) == "accepted"]
    missing_files = [str(base / name) for name in REVIEW_DISCOVERY_NAMES if not (base / name).exists()]
    parse_status = "ok" if selected.exists() and not warnings else "warning" if selected.exists() else "missing_review_package"
    return {
        "status": parse_status,
        "phase": "2G-1",
        "discovered_review_files": [str(path) for path in discovered],
        "selected_review_package": str(selected),
        "needs_edit_count": len(needs_edit),
        "existing_accepted_count": len(existing_accepted),
        "target_accepted_count": int(target_accepted_count),
        "parse_status": parse_status,
        "loader_warnings": warnings,
        "missing_files": missing_files,
        "database_written": False,
        "external_api_called": False,
        "_records": records,
        "_needs_edit_records": needs_edit,
        "_existing_accepted_records": existing_accepted,
    }


def _duplicate_keys(existing_accepted: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for record in existing_accepted:
        key = _dedup_key(record)
        if key:
            keys.add(key)
        unit_type = _text(record.get("unit_type"))
        canonical = _norm(record.get("canonical_name") or record.get("title"))
        if unit_type and canonical:
            keys.add(f"{unit_type}:{canonical}")
    return keys


def _source_overlap(record: dict[str, Any]) -> bool:
    content = _normalized_content(record.get("content")).lower()
    source = _source_preview(record).lower()
    if not content or not source:
        return False
    if content in source:
        return True
    tokens = {token for token in re.split(r"[^0-9a-zA-Z_]+", content) if len(token) > 3}
    source_tokens = {token for token in re.split(r"[^0-9a-zA-Z_]+", source) if len(token) > 3}
    if not tokens or not source_tokens:
        return False
    return len(tokens & source_tokens) / max(1, min(len(tokens), len(source_tokens))) >= 0.75


def _content_blockers(record: dict[str, Any]) -> list[str]:
    content = _normalized_content(record.get("content"))
    blockers: list[str] = []
    if len(content) < 25:
        blockers.append("content_too_short")
    if len(content) > 220:
        blockers.append("content_too_long_or_multi_fact")
    if FRAGMENT_START_RE.search(content):
        blockers.append("content_starts_as_fragment")
    if TRAILING_FRAGMENT_RE.search(content):
        blockers.append("content_ends_as_fragment")
    if OCR_GARBAGE_RE.search(content):
        blockers.append("ocr_or_encoding_artifact_present")
    if content.count("*") >= 2:
        blockers.append("bullet_list_not_atomic")
    return blockers


def _unit_type_blockers(record: dict[str, Any]) -> list[str]:
    unit_type = _text(record.get("unit_type"))
    canonical = _norm(record.get("canonical_name") or record.get("title"))
    content = _normalized_content(record.get("content"))
    blockers: list[str] = []
    if unit_type not in VALID_UNIT_TYPES:
        return ["invalid_unit_type"]
    if unit_type == "parameter":
        if canonical not in PARAMETER_TERMS and not NUMERIC_OR_UNIT_RE.search(content):
            blockers.append("parameter_lacks_value_unit_or_known_parameter_name")
        if not NUMERIC_OR_UNIT_RE.search(content):
            blockers.append("parameter_without_value_or_unit")
    elif unit_type == "fault_case":
        if not FAULT_RE.search(f"{canonical} {content}"):
            blockers.append("fault_case_lacks_fault_signal")
    elif unit_type == "component":
        if canonical not in COMPONENT_TERMS:
            blockers.append("component_canonical_not_whitelisted_for_auto_accept")
    elif unit_type == "concept":
        if not CONCEPT_MARKER_RE.search(content):
            blockers.append("concept_lacks_definition_or_clear_relation")
    return blockers


def _strict_acceptance_blockers(record: dict[str, Any], duplicate_key_set: set[str]) -> list[str]:
    blockers: list[str] = []
    candidate_id = _candidate_id(record)
    if not candidate_id:
        blockers.append("missing_candidate_id")
    if not _dedup_key(record):
        blockers.append("missing_dedup_key")
    if not _text(record.get("canonical_name")):
        blockers.append("missing_canonical_name")
    if not _text(record.get("unit_type")):
        blockers.append("missing_unit_type")
    if not _text(record.get("document_id")):
        blockers.append("missing_document_id")
    if not _text(record.get("source_chunk_id")):
        blockers.append("missing_source_chunk_id")
    if _text(record.get("provenance_status")) != "ready":
        blockers.append("provenance_not_ready")
    if not _source_preview(record):
        blockers.append("missing_source_text_preview")
    if not _source_overlap(record):
        blockers.append("source_support_not_strict_enough")

    key = _dedup_key(record)
    identity_key = f"{_text(record.get('unit_type'))}:{_norm(record.get('canonical_name'))}"
    if key in duplicate_key_set or identity_key in duplicate_key_set:
        blockers.append("duplicate_with_existing_accepted")

    severe_flags = sorted(SEVERE_ACCEPTED_FLAGS.intersection(_quality_flags(record)))
    blockers.extend(f"severe_quality_flag:{flag}" for flag in severe_flags)
    blockers.extend(_content_blockers(record))
    blockers.extend(_unit_type_blockers(record))

    validation = validate_review_record({**record, "review_status": "accepted"})
    for issue in validation.get("errors") or []:
        blockers.append(f"accepted_validator:{issue.get('error_type')}")
    return sorted(set(blockers))


def _classification_from_blockers(record: dict[str, Any], blockers: list[str]) -> str:
    action = _text(record.get("suggested_action")).lower()
    risk = _text(record.get("risk_level")).lower()
    if "duplicate_with_existing_accepted" in blockers:
        return "duplicate_suggested"
    if action in REJECT_ACTIONS or risk == "high":
        return "reject_suggested"
    if not blockers and action in PROMOTE_ACTIONS:
        return "auto_acceptable"
    return "needs_human_review"


def strict_auto_review_candidates(
    needs_edit_records: list[dict[str, Any]],
    existing_accepted_records: list[dict[str, Any]],
    *,
    runs_dir: str | Path = RUNS_DIR,
) -> dict[str, Any]:
    duplicate_key_set = _duplicate_keys(existing_accepted_records)
    normalized = [_normalize_review_record(record) for record in needs_edit_records]
    provenance = backfill_candidates_provenance(normalized, str(runs_dir)) if normalized else {"candidates": []}
    enhanced = [dict(record) for record in provenance.get("candidates") or [] if isinstance(record, dict)]

    suggestions: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    blocked_reasons: Counter[str] = Counter()
    fix_applied_count = 0
    fix_suggestions_count = 0

    for original, record in zip(needs_edit_records, enhanced):
        item = _normalize_review_record(record)
        blockers = _strict_acceptance_blockers(item, duplicate_key_set)
        classification = _classification_from_blockers(item, blockers)
        counts[classification] += 1
        for blocker in blockers:
            blocked_reasons[blocker] += 1
        if _text(original.get("canonical_name")) != _text(item.get("canonical_name")) or _text(original.get("content")) != _text(item.get("content")):
            fix_applied_count += 1
        if blockers:
            fix_suggestions_count += 1

        suggestions.append(
            {
                **item,
                "auto_review_classification": classification,
                "strict_blockers": blockers,
                "review_method": AUTO_REVIEW_METHOD if classification == "auto_acceptable" else "rule_based_triage",
                "review_notes": _review_notes(classification, blockers),
                "auto_review_is_rule_based": True,
                "human_review_faked": False,
                "database_written": False,
            }
        )

    return {
        "status": "ok",
        "phase": "2G-1",
        "input_needs_edit_count": len(needs_edit_records),
        "auto_acceptable_count": counts.get("auto_acceptable", 0),
        "needs_human_review_count": counts.get("needs_human_review", 0),
        "reject_suggested_count": counts.get("reject_suggested", 0),
        "duplicate_suggested_count": counts.get("duplicate_suggested", 0),
        "fix_applied_count": fix_applied_count,
        "fix_suggestions_count": fix_suggestions_count,
        "blocked_reasons": dict(sorted(blocked_reasons.items())),
        "auto_review_is_rule_based": True,
        "human_review_faked": False,
        "database_written": False,
        "external_api_called": False,
        "_suggestions": suggestions,
    }


def _review_notes(classification: str, blockers: list[str]) -> str:
    if classification == "auto_acceptable":
        return "Accepted by strict deterministic rules; not human reviewed."
    if classification == "duplicate_suggested":
        return "Suggested duplicate; keep out of accepted pack until reviewed."
    if classification == "reject_suggested":
        return "Suggested reject due to high risk, reject hint, or strict quality blockers."
    return "Needs human review; strict auto-review blockers remain: " + ", ".join(blockers[:8])


def build_reviewed_candidates_from_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviewed: list[dict[str, Any]] = []
    for item in suggestions:
        classification = _text(item.get("auto_review_classification"))
        if classification == "auto_acceptable":
            status = "accepted"
            method = AUTO_REVIEW_METHOD
            blocked_reason = ""
        elif classification == "reject_suggested":
            status = "rejected_suggested"
            method = "rule_based_triage"
            blocked_reason = "reject_suggested"
        elif classification == "duplicate_suggested":
            status = "duplicate_suggested"
            method = "rule_based_triage"
            blocked_reason = "duplicate_suggested"
        else:
            status = "needs_human_review"
            method = "rule_based_triage"
            blocked_reason = ",".join(item.get("strict_blockers") or [])

        reviewed.append(
            {
                "candidate_id": item.get("candidate_id"),
                "unit_code": item.get("unit_code"),
                "dedup_key": item.get("dedup_key"),
                "unit_type": item.get("unit_type"),
                "canonical_name": item.get("canonical_name"),
                "title": item.get("title") or str(item.get("canonical_name") or "").replace("_", " "),
                "content": item.get("content"),
                "source_text_preview": item.get("source_text_preview"),
                "document_id": item.get("document_id"),
                "source_chunk_id": item.get("source_chunk_id"),
                "source_run_name": item.get("source_run_name") or item.get("run_name"),
                "source_reviewed_file": item.get("source_reviewed_file"),
                "provenance_status": item.get("provenance_status"),
                "review_status": status,
                "review_method": method,
                "review_notes": item.get("review_notes"),
                "quality_flags": item.get("quality_flags") if isinstance(item.get("quality_flags"), list) else [],
                "blocked_reason": blocked_reason,
                "strict_blockers": item.get("strict_blockers") or [],
                "auto_review_is_rule_based": True,
                "human_review_faked": False,
                "database_written": False,
            }
        )
    return reviewed


def build_phase2g1_accepted_pack(
    existing_accepted_records: list[dict[str, Any]],
    reviewed_candidates: list[dict[str, Any]],
    *,
    target_accepted_count: int = TARGET_ACCEPTED_COUNT,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    accepted_by_auto = 0
    accepted_by_human = 0
    skipped_needs_human = 0
    rejected = 0
    duplicates = 0
    provenance_missing = 0

    def add(record: dict[str, Any]) -> bool:
        key = _dedup_key(record) or _candidate_id(record)
        if not key or key in seen:
            return False
        seen.add(key)
        accepted.append(dict(record))
        return True

    for record in existing_accepted_records:
        if _status(record) == "accepted":
            item = _normalize_review_record(record)
            item.setdefault("review_method", "human_reviewed_or_legacy_accepted")
            if _text(item.get("provenance_status")) != "ready":
                # Existing accepted pack is provenance-backfilled by writer/readback paths.
                item.setdefault("provenance_status", "ready")
            if add(item):
                accepted_by_human += 1

    for record in reviewed_candidates:
        if _status(record) == "accepted" and _text(record.get("provenance_status")) == "ready":
            if add(_normalize_review_record(record)):
                accepted_by_auto += 1
        elif _status(record) == "needs_human_review":
            skipped_needs_human += 1
        elif _status(record) == "rejected_suggested":
            rejected += 1
        elif _status(record) == "duplicate_suggested":
            duplicates += 1
        if _status(record) == "accepted" and _text(record.get("provenance_status")) != "ready":
            provenance_missing += 1

    ready_count = sum(1 for record in accepted if _text(record.get("provenance_status")) in {"", "ready"})
    accepted_after = len(accepted)
    return {
        "status": "ok",
        "phase": "2G-1",
        "accepted_count_before": len([record for record in existing_accepted_records if _status(record) == "accepted"]),
        "accepted_count_added": accepted_by_auto,
        "accepted_count_after_phase2g1": accepted_after,
        "target_accepted_count": int(target_accepted_count),
        "minimum_write_threshold": MIN_WRITE_THRESHOLD,
        "reached_target": accepted_after >= int(target_accepted_count),
        "accepted_by_human_count": accepted_by_human,
        "accepted_by_auto_strict_rule_count": accepted_by_auto,
        "skipped_needs_human_review_count": skipped_needs_human,
        "rejected_suggested_count": rejected,
        "duplicate_suggested_count": duplicates,
        "provenance_ready_count": ready_count,
        "provenance_missing_count": provenance_missing,
        "can_attempt_write": accepted_after >= MIN_WRITE_THRESHOLD and provenance_missing == 0,
        "write_scope": "phase2g1_accepted_pack" if accepted_after >= MIN_WRITE_THRESHOLD else "skipped_below_minimum_write_threshold",
        "database_written": False,
        "external_api_called": False,
        "_accepted_records": accepted,
    }


__all__ = [
    "AUTO_REVIEW_METHOD",
    "MIN_WRITE_THRESHOLD",
    "build_phase2g1_accepted_pack",
    "build_reviewed_candidates_from_suggestions",
    "discover_phase2g_review_package",
    "strict_auto_review_candidates",
]
