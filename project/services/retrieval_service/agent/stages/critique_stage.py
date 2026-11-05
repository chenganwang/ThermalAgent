from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from ...critique.workflow import run_critique_workflow
from ..metadata_builder import ensure_metadata_contract, package_self_critique_metadata, safe_error
from ..state import AgentContext
from .base import BaseAgentStage


class CritiqueStage(BaseAgentStage):
    """Run the existing text-only critique workflow behind a stage boundary."""

    name = "critique"

    def __init__(
        self,
        *,
        workflow_runner: Callable[..., dict[str, Any]] = run_critique_workflow,
        enable_repair: bool = True,
        max_repair_attempts: int = 1,
    ) -> None:
        self.workflow_runner = workflow_runner
        self.enable_repair = bool(enable_repair)
        self.max_repair_attempts = int(max_repair_attempts)

    def run(self, context: AgentContext) -> AgentContext:
        context.metadata = ensure_metadata_contract(context.metadata)
        try:
            raw_result = self.workflow_runner(
                query=context.request.query,
                answer=context.answer,
                sources=deepcopy(context.sources),
                metadata=deepcopy(context.metadata),
                task=deepcopy(context.task),
                rewrite=deepcopy(context.rewrite),
                enable_repair=self.enable_repair,
                max_repair_attempts=self.max_repair_attempts,
            )
            result = package_self_critique_metadata(dict(raw_result or {}))
        except Exception as exc:
            error = safe_error(exc)
            context.errors.append(f"{self.name}: {error}")
            result = package_self_critique_metadata(self._failure_result(context.answer, error))

        context.metadata["self_critique"] = result
        context.intermediate["critique_result"] = deepcopy(result)
        context.intermediate["safe_repair_result"] = self._repair_summary(result)
        if result.get("repaired") and result.get("final_answer"):
            context.answer = str(result["final_answer"])
        return context

    @staticmethod
    def _repair_summary(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "repaired": bool(result.get("repaired")),
            "safe_repair_applied": bool(result.get("safe_repair_applied") or result.get("repaired")),
            "repair_action": str(result.get("repair_action") or "none"),
            "repair_attempts": int(result.get("repair_attempts") or 0),
            "original_route": result.get("original_route"),
            "final_route": result.get("final_route") or result.get("route"),
            "warnings": list(result.get("warnings") or []),
            "errors": list(result.get("errors") or []),
        }

    @staticmethod
    def _failure_result(answer: str, error: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "passed": False,
            "severity": "error",
            "issues": [],
            "repair_action": "none",
            "route": "finalize_with_warning",
            "requires_human_review": False,
            "workflow": {"enabled": False, "version": "critic_workflow_v1"},
            "trace": [],
            "repair_attempts": 0,
            "repaired": False,
            "original_answer": answer,
            "final_answer": answer,
            "original_route": "finalize_with_warning",
            "final_route": "finalize_with_warning",
            "error": error,
        }


__all__ = ["CritiqueStage"]
