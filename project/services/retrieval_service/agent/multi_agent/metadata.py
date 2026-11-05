from __future__ import annotations

from typing import Any

from ..state import AgentContext
from .supervisor_runner import run_supervisor_shadow


def default_multi_agent_metadata() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": "disabled",
        "uses_llm": False,
        "plan": None,
        "role_cards": [],
        "worker_trace": [],
        "warnings": [],
        "errors": [],
    }


def attach_multi_agent_metadata(context: AgentContext) -> AgentContext:
    """Attach only the shadow-observability payload to the existing metadata."""

    result = run_supervisor_shadow(context)
    if not isinstance(context.metadata, dict):
        context.metadata = {}
    context.metadata["multi_agent"] = result.to_dict()
    return context


__all__ = ["attach_multi_agent_metadata", "default_multi_agent_metadata"]
