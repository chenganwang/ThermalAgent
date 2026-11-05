from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import AgentRequest


@dataclass
class AgentContext:
    """Mutable state passed between AgentPipeline stages."""

    request: AgentRequest
    task: dict[str, Any] = field(default_factory=dict)
    rewrite: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    intermediate: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["AgentContext"]
