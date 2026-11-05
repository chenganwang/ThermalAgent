from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DemoCase:
    case_id: str
    title: str
    category: str
    query: str
    expected_task_type: str | None = None
    expected_tools: list[str] = field(default_factory=list)
    expected_metadata_paths: list[str] = field(default_factory=list)
    expected_cards: list[str] = field(default_factory=list)
    expected_warnings: list[str] = field(default_factory=list)
    boundary_notes: list[str] = field(default_factory=list)
    should_not_include: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("case_id", "title", "category", "query"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DemoCase":
        return cls(
            case_id=str(value.get("case_id") or ""),
            title=str(value.get("title") or ""),
            category=str(value.get("category") or ""),
            query=str(value.get("query") or ""),
            expected_task_type=value.get("expected_task_type"),
            expected_tools=list(value.get("expected_tools") or []),
            expected_metadata_paths=list(value.get("expected_metadata_paths") or []),
            expected_cards=list(value.get("expected_cards") or []),
            expected_warnings=list(value.get("expected_warnings") or []),
            boundary_notes=list(value.get("boundary_notes") or []),
            should_not_include=list(value.get("should_not_include") or []),
        )


@dataclass
class DemoCaseRunResult:
    case_id: str
    passed: bool
    query: str
    top_level_contract_ok: bool
    expected_tools_found: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    metadata_paths_found: list[str] = field(default_factory=list)
    missing_metadata_paths: list[str] = field(default_factory=list)
    cards_generated: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    response_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["DemoCase", "DemoCaseRunResult"]
