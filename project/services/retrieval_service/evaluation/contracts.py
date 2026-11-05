from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DemoQAItem:
    case_id: str
    category: str
    query: str
    expected_task_type: str | None = None
    expected_tools: list[str] = field(default_factory=list)
    expected_metadata_paths: list[str] = field(default_factory=list)
    expected_cards: list[str] = field(default_factory=list)
    expected_status: str | None = None
    required_warnings: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    scoring_focus: list[str] = field(default_factory=list)
    boundary_notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("case_id", "category", "query"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DemoQAItem":
        return cls(
            case_id=str(value.get("case_id") or ""),
            category=str(value.get("category") or ""),
            query=str(value.get("query") or ""),
            expected_task_type=value.get("expected_task_type"),
            expected_tools=list(value.get("expected_tools") or []),
            expected_metadata_paths=list(value.get("expected_metadata_paths") or []),
            expected_cards=list(value.get("expected_cards") or []),
            expected_status=value.get("expected_status"),
            required_warnings=list(value.get("required_warnings") or []),
            forbidden_claims=list(value.get("forbidden_claims") or []),
            scoring_focus=list(value.get("scoring_focus") or []),
            boundary_notes=list(value.get("boundary_notes") or []),
        )


@dataclass
class DemoQAEvaluationResult:
    case_id: str
    category: str
    passed: bool = False
    score: float = 0.0
    task_type_ok: bool = False
    tool_selection_ok: bool = False
    metadata_contract_ok: bool = False
    missing_params_ok: bool = False
    forbidden_claims_ok: bool = False
    cards_ok: bool = False
    self_critique_ok: bool = False
    multi_agent_ok: bool = False
    top_level_contract_ok: bool = False
    retrieval_count_ok: bool = False
    json_serializable_ok: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    response_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DemoQASummary:
    total: int
    passed: int
    failed: int
    pass_rate: float = 0.0
    average_score: float = 0.0
    category_scores: dict[str, Any] = field(default_factory=dict)
    metric_scores: dict[str, float] = field(default_factory=dict)
    failure_cases: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["DemoQAEvaluationResult", "DemoQAItem", "DemoQASummary"]
