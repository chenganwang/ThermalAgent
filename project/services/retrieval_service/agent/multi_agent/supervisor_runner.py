from __future__ import annotations

from ..state import AgentContext
from .contracts import SupervisorRunResult
from .role_cards import list_role_cards
from .supervisor_planner import build_supervisor_plan
from .trace_builder import build_worker_trace


def run_supervisor_shadow(context: AgentContext) -> SupervisorRunResult:
    """Observe final pipeline state without executing or mutating workers."""

    role_cards = list_role_cards()
    plan = build_supervisor_plan(
        query=context.request.query,
        task=context.task,
        rewrite=context.rewrite,
        metadata=context.metadata,
    )
    worker_trace = build_worker_trace(context, plan, role_cards)
    return SupervisorRunResult(
        enabled=True,
        mode="shadow",
        uses_llm=False,
        plan=plan.to_dict(),
        role_cards=[card.to_dict() for card in role_cards],
        worker_trace=[record.to_dict() for record in worker_trace],
        warnings=[],
        errors=[],
    )


__all__ = ["run_supervisor_shadow"]
