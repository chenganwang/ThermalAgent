from __future__ import annotations

from typing import Any


SAFE_TYPES = {
    "routing_issues": "routing_priority_adjustment",
    "tool_selection_issues": "task_intent_rule_tightening",
    "metadata_contract_issues": "metadata_default_backfill",
    "report_or_card_issues": "frontend_card_visibility_fix",
    "forbidden_claim_issues": "forbidden_claim_filter_fix",
    "dataset_expectation_issues": "evaluation_summary_fix",
}

UNSAFE_TYPES = {
    "invent_property_data", "invent_pump_curve", "invent_thermal_resistance",
    "fake_cfd_result", "weaken_forbidden_claims", "remove_failing_case",
    "loosen_contract_without_reason",
}

ALLOWED_FILES = {
    "routing_priority_adjustment": ["services/retrieval_service/task_understanding.py", "services/retrieval_service/task/"],
    "task_intent_rule_tightening": ["services/retrieval_service/task/", "services/retrieval_service/tools/router.py"],
    "metadata_default_backfill": ["services/retrieval_service/agent/metadata_builder.py"],
    "frontend_card_visibility_fix": ["services/retrieval_service/demo_cases/frontend_cards.py"],
    "report_render_hint_fix": ["services/retrieval_service/analysis/report_templates.py"],
    "forbidden_claim_filter_fix": ["services/retrieval_service/critique/"],
    "evaluation_summary_fix": ["services/retrieval_service/evaluation/"],
}

FORBIDDEN_FILES = [
    "services/retrieval_service/retriever.py", "services/retrieval_service/rag_chain.py",
    "services/retrieval_service/properties/", "data/", "frontends/", "runtime/",
]


def classify_safe_fix(triage_item: dict[str, Any]) -> dict[str, Any]:
    explicit = str(triage_item.get("fix_type") or "")
    if explicit in UNSAFE_TYPES:
        return {
            "safe_to_fix": False,
            "fix_type": explicit,
            "allowed_files": [],
            "forbidden_files": list(FORBIDDEN_FILES),
            "required_tests": ["python scripts/test_demoqa_evaluation_smoke.py"],
            "rationale": "The proposed change would fabricate evidence, weaken the benchmark, or remove a failing case.",
            "priority": "blocked",
        }
    classifications = list(triage_item.get("classifications") or [])
    candidates = list(triage_item.get("safe_fix_types") or [])
    fix_type = candidates[0] if candidates else next(
        (SAFE_TYPES[value] for value in classifications if value in SAFE_TYPES),
        explicit or "manual_business_review",
    )
    safe = fix_type in ALLOWED_FILES and not triage_item.get("unsafe_reasons")
    critical = "forbidden_claim_issues" in classifications or fix_type == "forbidden_claim_filter_fix"
    return {
        "safe_to_fix": safe,
        "fix_type": fix_type,
        "allowed_files": list(ALLOWED_FILES.get(fix_type, [])),
        "forbidden_files": list(FORBIDDEN_FILES),
        "required_tests": [
            "python scripts/test_task_understanding_service.py",
            "python scripts/test_demoqa_evaluation_smoke.py",
            "python scripts/evaluate_thermalagent_demoqa_50.py",
        ],
        "rationale": (
            "Low-risk contract/routing repair is possible, but the dataset and safety assertions must remain unchanged."
            if safe else "Requires manual business-logic design or evidence that is outside the safe auto-fix boundary."
        ),
        "priority": "critical" if critical else ("normal" if safe else "manual_review"),
    }


__all__ = ["ALLOWED_FILES", "SAFE_TYPES", "UNSAFE_TYPES", "classify_safe_fix"]
