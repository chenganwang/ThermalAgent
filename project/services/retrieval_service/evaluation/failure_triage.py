from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any


def _metric_for_failure(failure: str) -> str:
    if failure.startswith("task_type_mismatch"):
        return "task_type"
    if failure.startswith("missing_tool"):
        return "tool_selection"
    if failure.startswith("missing_metadata_path"):
        return "metadata_contract"
    if failure.startswith("status_mismatch") or failure.startswith("required_warning_missing"):
        return "missing_params_or_status"
    if failure.startswith("missing_card"):
        return "card_generation"
    if failure.startswith("forbidden_claim"):
        return "forbidden_claims"
    return "other"


def _classify_case(case: dict[str, Any]) -> dict[str, Any]:
    failures = [str(value) for value in case.get("failures") or []]
    metrics = sorted({_metric_for_failure(value) for value in failures})
    classifications: list[str] = []
    if any(value.startswith("forbidden_claim") for value in failures):
        classifications.append("forbidden_claim_issues")
    if any(value.startswith("task_type_mismatch") for value in failures):
        classifications.append("routing_issues")
    if any(value.startswith("missing_tool") for value in failures):
        classifications.append("tool_selection_issues")
    missing_metadata = [value for value in failures if value.startswith("missing_metadata_path")]
    if missing_metadata:
        status = (case.get("response_summary") or {}).get("metadata_status") or {}
        inactive_target = False
        for failure in missing_metadata:
            parts = failure.split(":", 1)[-1].split(".")
            block = status.get(parts[1]) if len(parts) > 1 and isinstance(status, dict) else None
            if not isinstance(block, dict) or (
                block.get("enabled") is False or block.get("generated") is False
            ):
                inactive_target = True
        classifications.append("routing_issues" if inactive_target else "metadata_contract_issues")
    if any(value.startswith("missing_card") for value in failures):
        classifications.append("report_or_card_issues")
    if any(value.startswith("status_mismatch") or value.startswith("required_warning_missing") for value in failures):
        classifications.append("business_logic_issues")
    if case.get("category") == "self_critique_overclaim_guard" and failures and all(
        value.startswith("missing_card") for value in failures
    ):
        classifications = ["dataset_expectation_issues"]

    safe_types = {
        "routing_issues": "task_intent_rule_tightening",
        "tool_selection_issues": "routing_priority_adjustment",
        "metadata_contract_issues": "metadata_default_backfill",
        "report_or_card_issues": "frontend_card_visibility_fix",
        "forbidden_claim_issues": "forbidden_claim_filter_fix",
        "dataset_expectation_issues": "evaluation_summary_fix",
    }
    safe_candidates = [safe_types[value] for value in classifications if value in safe_types]
    unsafe_reasons: list[str] = []
    text = json.dumps(case, ensure_ascii=False).lower()
    if any(token in text for token in ("invent_property_data", "invent_pump_curve", "fake_cfd_result")):
        unsafe_reasons.append("requires_prohibited_fabrication")
    return {
        "case_id": case.get("case_id"),
        "category": case.get("category"),
        "score": case.get("score"),
        "failures": failures,
        "failed_metrics": metrics,
        "classifications": classifications or ["business_logic_issues"],
        "safe_fix_types": safe_candidates,
        "unsafe_reasons": unsafe_reasons,
        "recommended_action": (
            "review_low_risk_contract_or_routing_fix" if safe_candidates
            else "retain_as_business_gap_and_require_manual_design"
        ),
    }


def triage_demoqa_failures(
    eval_json_path: Path | str,
    failures_json_path: Path | str | None = None,
) -> dict[str, Any]:
    eval_payload = json.loads(Path(eval_json_path).read_text(encoding="utf-8"))
    if failures_json_path is not None:
        failures = json.loads(Path(failures_json_path).read_text(encoding="utf-8"))
    else:
        failures = [value for value in eval_payload.get("results", []) if not value.get("passed")]
    if not isinstance(failures, list):
        raise ValueError("DemoQA failures payload must be a list")
    triaged = [_classify_case(case) for case in failures]
    by_category = Counter(str(case.get("category") or "unknown") for case in failures)
    by_metric = Counter(metric for item in triaged for metric in item["failed_metrics"])
    by_root = Counter(value for item in triaged for value in item["classifications"])

    def selected(name: str) -> list[dict[str, Any]]:
        return [item for item in triaged if name in item["classifications"]]

    safe = [item for item in triaged if item["safe_fix_types"] and not item["unsafe_reasons"]]
    unsafe = [item for item in triaged if item["unsafe_reasons"] or not item["safe_fix_types"]]
    return {
        "total_failures": len(triaged),
        "failure_cases": triaged,
        "failure_by_category": dict(sorted(by_category.items())),
        "failure_by_metric": dict(sorted(by_metric.items())),
        "likely_root_causes": [
            {"root_cause": key, "count": value} for key, value in sorted(by_root.items())
        ],
        "safe_fix_candidates": safe,
        "unsafe_to_auto_fix": unsafe,
        "dataset_expectation_issues": selected("dataset_expectation_issues"),
        "business_logic_issues": selected("business_logic_issues"),
        "metadata_contract_issues": selected("metadata_contract_issues"),
        "routing_issues": selected("routing_issues"),
        "tool_selection_issues": selected("tool_selection_issues"),
        "forbidden_claim_issues": selected("forbidden_claim_issues"),
        "report_or_card_issues": selected("report_or_card_issues"),
        "recommended_next_actions": [
            "Keep forbidden-claim, top-level, retrieval-count, self-critique, and Multi-Agent gates at 100%.",
            "Review routing and explicit missing-input detection as separate small changes.",
            "Do not change dataset expectations before confirming the documented product contract.",
        ],
        "baseline": eval_payload.get("summary") or {},
    }


__all__ = ["triage_demoqa_failures"]
