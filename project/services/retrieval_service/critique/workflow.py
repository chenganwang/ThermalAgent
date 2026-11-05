from __future__ import annotations

from typing import Any

from .answer_critic import critique_answer
from .critique_router import route_by_critique
from .critique_state import CritiqueWorkflowState
from .repair_policy import is_safe_repair_action
from .safe_repair import safe_repair_answer


WORKFLOW_VERSION = "critic_workflow_v1"


def _error_text(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:400]


def _failure_result(error: str, trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "enabled": False,
        "passed": False,
        "severity": "error",
        "issues": [],
        "repair_action": "none",
        "route": "finalize_with_warning",
        "requires_human_review": False,
        "workflow": {
            "enabled": False,
            "version": WORKFLOW_VERSION,
            "repair_enabled": False,
            "max_repair_attempts": 0,
        },
        "trace": list(trace or []),
        "repair_attempts": 0,
        "repaired": False,
        "original_answer": "",
        "final_answer": "",
        "original_route": "finalize_with_warning",
        "final_route": "finalize_with_warning",
        "original_critique": {},
        "final_critique": {},
        "error": error,
    }


def run_critique_workflow(
    query: str,
    answer: str,
    sources: list[dict] | None = None,
    metadata: dict | None = None,
    task: dict | None = None,
    rewrite: dict | None = None,
    enable_repair: bool = False,
    max_repair_attempts: int = 0,
) -> dict[str, Any]:
    """Run the LangGraph-style hand-written critique workflow.

    Repair is limited to one low-risk text-only pass. It never mutates
    metadata, sources, tool results, indexes, or databases.
    """

    state: CritiqueWorkflowState | None = None
    try:
        repair_enabled = bool(enable_repair and int(max_repair_attempts or 0) >= 1)
        repair_limit = 1 if repair_enabled else 0
        state = CritiqueWorkflowState.create(
            query=query,
            answer=answer,
            sources=sources,
            metadata=metadata,
            task=task,
            rewrite=rewrite,
        )
        state.add_trace(
            "prepare_state",
            "ok",
            sources_count=len(state.sources),
            answer_chars=len(state.answer),
            repair_enabled=repair_enabled,
        )

        critique_result = critique_answer(
            query=state.query,
            answer=state.answer,
            sources=state.sources,
            metadata=state.metadata,
            task=state.task,
            rewrite=state.rewrite,
        )
        state.critique_result = dict(critique_result)
        state.add_trace(
            "critique_answer",
            "ok",
            severity=critique_result.get("severity"),
            issues_count=len(critique_result.get("issues") or []),
            repair_action=critique_result.get("repair_action"),
        )

        original_route = route_by_critique(critique_result, repair_attempts=state.repair_attempts)
        original_action = str(critique_result.get("repair_action") or "none")
        state.critique_result["route"] = original_route
        state.add_trace("route_by_critique", "ok", route=original_route)

        repaired = False
        final_critique = dict(state.critique_result)
        final_route = original_route
        state.final_answer = state.answer

        if repair_enabled and original_action != "none" and state.repair_attempts < repair_limit:
            if not is_safe_repair_action(original_action):
                state.add_trace("safe_repair_skipped", "ok", repair_action=original_action, reason="repair_action_not_safe")
            else:
                try:
                    repair_result = safe_repair_answer(
                        query=state.query,
                        answer=state.answer,
                        critique_result=state.critique_result,
                        metadata=state.metadata,
                        sources=state.sources,
                    )
                    state.add_trace(
                        "safe_repair",
                        "ok",
                        repair_action=original_action,
                        repaired=bool(repair_result.get("repaired")),
                        warnings=repair_result.get("warnings") or [],
                    )
                    if repair_result.get("repaired"):
                        state.repair_attempts += 1
                        repaired = True
                        state.final_answer = str(repair_result.get("repaired_answer") or state.answer)
                        after_repair = critique_answer(
                            query=state.query,
                            answer=state.final_answer,
                            sources=state.sources,
                            metadata=state.metadata,
                            task=state.task,
                            rewrite=state.rewrite,
                        )
                        state.add_trace(
                            "critique_after_repair",
                            "ok",
                            severity=after_repair.get("severity"),
                            issues_count=len(after_repair.get("issues") or []),
                            repair_action=after_repair.get("repair_action"),
                        )
                        final_critique = dict(after_repair)
                        final_route = route_by_critique(final_critique, repair_attempts=state.repair_attempts)
                        final_critique["route"] = final_route
                        state.add_trace("route_after_repair", "ok", route=final_route)
                    else:
                        state.add_trace("safe_repair_skipped", "ok", repair_action=original_action, reason="repair_returned_false")
                except Exception as exc:
                    error = _error_text(exc)
                    state.errors.append(error)
                    state.add_trace("safe_repair_error", "error", repair_action=original_action, error=error)

        state.add_trace("finalize", "ok", repaired=repaired, final_answer_unchanged=state.final_answer == state.answer)

        result = dict(final_critique)
        if repaired:
            result["repair_action"] = original_action
        result.update(
            {
                "workflow": {
                    "enabled": True,
                    "version": WORKFLOW_VERSION,
                    "repair_enabled": repair_enabled,
                    "max_repair_attempts": repair_limit,
                    "requested_repair": bool(enable_repair),
                    "requested_max_repair_attempts": int(max_repair_attempts or 0),
                },
                "trace": list(state.workflow_trace),
                "repair_attempts": state.repair_attempts,
                "repaired": repaired,
                "original_answer": state.answer,
                "final_answer": state.final_answer,
                "original_route": original_route,
                "final_route": final_route,
                "original_critique": state.critique_result,
                "final_critique": final_critique,
                "errors": list(state.errors),
            }
        )
        return result
    except Exception as exc:
        trace = state.workflow_trace if state is not None else []
        if state is not None:
            state.errors.append(_error_text(exc))
            state.add_trace("workflow_error", "error", error=_error_text(exc))
            trace = state.workflow_trace
        return _failure_result(_error_text(exc), trace=trace)


__all__ = ["WORKFLOW_VERSION", "run_critique_workflow"]
