from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


TOOL_STATUS_SUCCESS = "success"
TOOL_STATUS_MISSING_PARAMS = "missing_params"
TOOL_STATUS_FAILED = "failed"
TOOL_STATUS_SKIPPED = "skipped"
TOOL_STATUS_UNKNOWN_TOOL = "unknown_tool"

TOOL_EXECUTION_STATUSES = {
    TOOL_STATUS_SUCCESS,
    TOOL_STATUS_MISSING_PARAMS,
    TOOL_STATUS_FAILED,
    TOOL_STATUS_SKIPPED,
    TOOL_STATUS_UNKNOWN_TOOL,
}


@dataclass(frozen=True)
class ToolSpec:
    """Declarative metadata for a deterministic local thermal tool."""

    name: str
    domain: str
    description: str
    intent_keywords: list[str]
    required_params: list[str]
    optional_params: list[str]
    units: dict[str, str]
    formula: str
    executor: str
    output_fields: list[str]
    examples: list[str]
    warnings: list[str]
    display_name: str | None = None
    category: str = "calculation"
    deterministic: bool = True
    uses_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolExecutionResult:
    """Structured execution result for the ToolSpec tool layer."""

    tool_name: str | None
    status: str
    inputs: dict[str, Any]
    result: dict[str, Any] | None
    missing_parameters: list[str]
    assumptions: list[str]
    formula: str | None
    steps: list[str]
    warnings: list[str]
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "TOOL_EXECUTION_STATUSES",
    "TOOL_STATUS_FAILED",
    "TOOL_STATUS_MISSING_PARAMS",
    "TOOL_STATUS_SKIPPED",
    "TOOL_STATUS_SUCCESS",
    "TOOL_STATUS_UNKNOWN_TOOL",
    "ToolExecutionResult",
    "ToolSpec",
]
