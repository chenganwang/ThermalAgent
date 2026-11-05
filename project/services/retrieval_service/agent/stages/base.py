from __future__ import annotations

from typing import Protocol

from ..state import AgentContext


class AgentStage(Protocol):
    name: str

    def run(self, context: AgentContext) -> AgentContext:
        ...


class BaseAgentStage:
    """No-op stage base for gradual pipeline migration."""

    name = "base"

    def run(self, context: AgentContext) -> AgentContext:
        return context


__all__ = ["AgentStage", "BaseAgentStage"]
