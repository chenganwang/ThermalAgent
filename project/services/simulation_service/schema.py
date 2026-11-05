from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"Unsupported model value: {type(value)!r}")


class _JsonModel(BaseModel):
    class Config:
        extra = "forbid"

    def to_dict(self) -> dict[str, Any]:
        return model_to_dict(self)


class SimulationTool(_JsonModel):
    tool_name: str
    display_name: str
    category: str = "simulation"
    description: str
    adapter_name: str = "mock"
    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0"
    enabled: bool = True
    mock_supported: bool = True
    real_backend_supported: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class SimulationRunRequestSchema(_JsonModel):
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    requested_backend: str = "mock"
    allow_mock: bool = True
    trace_id: str | None = None
    user_query: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationRunResult(_JsonModel):
    run_id: str
    task_id: str
    tool_name: str
    adapter_name: str
    backend_type: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    raw_output: dict[str, Any] = Field(default_factory=dict)
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str | None = None
    elapsed_ms: int | None = None
    trace_id: str | None = None
    is_mock: bool = False
    software: str | None = None
    software_version: str | None = None
    model_version: str | None = None


class SimulationHistoryRecord(_JsonModel):
    history_id: str
    run_id: str
    task_id: str
    user_query: str | None = None
    request: dict[str, Any]
    result: dict[str, Any]
    status: str
    error: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdapterStatus(_JsonModel):
    adapter_name: str
    available: bool
    backend_type: str
    reason: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    supported_tools: list[str] = Field(default_factory=list)
    supports_real_backend: bool = False
    supports_mock: bool = False
    requires_external_software: bool = False
    external_software_name: str | None = None
    external_software_available: bool = True
    checked_at: str = Field(default_factory=utc_now_iso)


__all__ = [
    "AdapterStatus",
    "SimulationHistoryRecord",
    "SimulationRunRequestSchema",
    "SimulationRunResult",
    "SimulationTool",
    "model_to_dict",
    "utc_now_iso",
]
