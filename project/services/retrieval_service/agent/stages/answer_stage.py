from __future__ import annotations

from ..metadata_builder import ensure_metadata_contract
from ..state import AgentContext
from .base import BaseAgentStage


class AnswerStage(BaseAgentStage):
    """Finalize answer text and metadata without executing business work."""

    name = "answer"

    _FALLBACK_ANSWER = (
        "No final answer is available from the current evidence. "
        "No calculation, property value, source, or simulation result has been inferred."
    )

    def run(self, context: AgentContext) -> AgentContext:
        answer = context.answer if isinstance(context.answer, str) else str(context.answer or "")
        fallback_used = not answer.strip()
        if fallback_used:
            answer = self._FALLBACK_ANSWER

        context.answer = answer
        context.metadata = ensure_metadata_contract(context.metadata)
        context.intermediate["final_answer"] = answer
        context.intermediate["answer_fallback_used"] = fallback_used
        context.intermediate["response_preview"] = answer[:240]
        return context


__all__ = ["AnswerStage"]
