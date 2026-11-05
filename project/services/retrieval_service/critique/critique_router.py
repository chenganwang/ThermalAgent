from __future__ import annotations

from typing import Any, Mapping


def _issues(critique_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = critique_result.get("issues")
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def route_by_critique(critique_result: dict, repair_attempts: int = 0) -> str:
    """Return the next route for the current critic result.

    This second-stage router only suggests a route. It does not execute repair.
    """

    if not isinstance(critique_result, Mapping):
        return "finalize_with_warning"

    severity = str(critique_result.get("severity") or "").lower()
    requires_human_review = bool(critique_result.get("requires_human_review"))
    issue_list = _issues(critique_result)
    issue_types = {str(item.get("type") or "") for item in issue_list}

    if severity == "ok":
        return "finalize"

    if "source_insufficient" in issue_types:
        sources_empty = any((item.get("evidence") or {}).get("sources_count") == 0 for item in issue_list)
        if sources_empty and repair_attempts <= 0:
            return "safe_boundary_answer"

    if severity == "warning":
        return "finalize_with_warning"

    if severity == "error" and requires_human_review:
        return "human_review"

    if severity == "error":
        return "human_review"

    return "finalize_with_warning"


__all__ = ["route_by_critique"]
