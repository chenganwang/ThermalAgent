from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRequest:
    """Stable request contract for the staged agent pipeline."""

    query: str
    session_id: str | None = None
    top_k: int = 5
    analysis_report_mode: bool = False
    requested_outputs: list[str] = field(default_factory=list)
    uploaded_model_file_id: str | None = None
    uploaded_model_filename: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentResponse:
    """Stable response contract matching /agent/answer top-level fields."""

    answer: str
    query: str
    task_type: str
    retrieval_count: int
    task: dict[str, Any]
    rewrite: dict[str, Any]
    sources: list[dict[str, Any]]
    session_id: str | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["AgentRequest", "AgentResponse"]
