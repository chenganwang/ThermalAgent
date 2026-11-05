from __future__ import annotations


SAFE_REPAIR_ACTIONS = {
    "append_boundary_warning": {
        "safe": True,
        "description": "Append a generic engineering boundary note when the answer is otherwise acceptable.",
    },
    "replace_with_property_lookup_insufficient_source_template": {
        "safe": True,
        "description": "Replace unsupported property lookup numeric claims with an insufficient-source template.",
    },
    "replace_with_analogy_boundary_template": {
        "safe": True,
        "description": "Replace unsafe cross-domain analogy answers with a bounded teaching-analogy template.",
    },
    "remove_forbidden_claims": {
        "safe": True,
        "description": "Remove high-risk engineering claims and replace them with a boundary statement.",
    },
}

UNSAFE_REPAIR_ACTIONS = {
    "review_calculation_answer",
    "review_metadata_contract",
    "human_review",
    "modify_tool_result",
    "modify_sources",
    "modify_database",
    "modify_test_expected",
    "run_cfd",
    "generate_property_value",
}


def is_safe_repair_action(action: str) -> bool:
    return str(action or "") in SAFE_REPAIR_ACTIONS


def get_repair_policy(action: str) -> dict:
    normalized = str(action or "")
    if normalized in SAFE_REPAIR_ACTIONS:
        return {
            "action": normalized,
            "safe": True,
            "description": SAFE_REPAIR_ACTIONS[normalized]["description"],
        }
    return {
        "action": normalized,
        "safe": False,
        "description": "Repair action is not allowed in the current safe-repair policy.",
        "blocked": normalized in UNSAFE_REPAIR_ACTIONS or bool(normalized),
    }


__all__ = ["SAFE_REPAIR_ACTIONS", "UNSAFE_REPAIR_ACTIONS", "get_repair_policy", "is_safe_repair_action"]
