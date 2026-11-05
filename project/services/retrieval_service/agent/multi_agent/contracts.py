from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRoleCard:
    role_id: str
    name: str
    description: str
    responsibilities: list[str]
    inputs: list[str]
    outputs: list[str]
    boundaries: list[str]
    stage_name: str | None
    uses_llm: bool = False
    uses_tools: bool = False

    def __post_init__(self) -> None:
        if not self.role_id.strip():
            raise ValueError("role_id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerExecutionRecord:
    worker_id: str
    role_id: str
    stage_name: str
    status: str
    started: bool
    completed: bool
    skipped: bool
    error_count: int
    warnings: list[str] = field(default_factory=list)
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, str):
            raise TypeError("status must be a string")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupervisorPlan:
    plan_id: str
    mode: str
    query_type: str
    selected_workers: list[str]
    skipped_workers: list[str]
    rationale: list[str]
    created_by: str = "rule_based_supervisor"
    uses_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupervisorRunResult:
    enabled: bool
    mode: str
    plan: dict[str, Any]
    role_cards: list[dict[str, Any]]
    worker_trace: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    uses_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "AgentRoleCard",
    "SupervisorPlan",
    "SupervisorRunResult",
    "WorkerExecutionRecord",
]
