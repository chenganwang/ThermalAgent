from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SIMULATION_STATUS_SUCCESS = "success"
SIMULATION_STATUS_MISSING_PARAMS = "missing_params"
SIMULATION_STATUS_FAILED = "failed"
SIMULATION_STATUS_UNAVAILABLE = "unavailable"
SIMULATION_STATUS_TIMEOUT = "timeout"

SIMULATION_STATUSES = {
    SIMULATION_STATUS_SUCCESS,
    SIMULATION_STATUS_MISSING_PARAMS,
    SIMULATION_STATUS_FAILED,
    SIMULATION_STATUS_UNAVAILABLE,
    SIMULATION_STATUS_TIMEOUT,
}


@dataclass(frozen=True)
class SimulationToolSpec:
    tool_name: str
    display_name: str
    description: str
    software: str
    default_adapter: str
    supported_adapters: list[str]
    required_inputs: list[str]
    optional_inputs: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    supports_mock: bool = True
    enabled: bool = True
    version: str = "1.0"
    warnings: list[str] = field(default_factory=list)
    category: str = "simulation"
    tags: list[str] = field(default_factory=list)
    mock_supported: bool = True
    real_backend_supported: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mock_supported"] = self.supports_mock or self.mock_supported
        return data


@dataclass(frozen=True)
class SimulationRunRequest:
    tool_name: str
    inputs: dict[str, Any]
    session_id: str | None = None
    user_query: str | None = None
    adapter_name: str | None = None
    mode: str = "mock"
    timeout_seconds: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    requested_backend: str | None = None
    allow_mock: bool = True
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimulationAdapterResult:
    tool_name: str
    adapter_name: str
    status: str
    mocked: bool
    raw_result: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int | None = None
    backend_type: str | None = None
    raw_output: dict[str, Any] = field(default_factory=dict)
    software: str | None = None
    software_version: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SIMULATION_STATUSES:
            raise ValueError(f"unsupported simulation status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimulationResultEnvelope:
    task_id: str
    job_id: str | None
    tool_name: str
    adapter_name: str
    status: str
    mocked: bool
    inputs: dict[str, Any]
    result: dict[str, Any]
    artifacts: list[dict[str, Any]]
    warnings: list[str]
    errors: list[dict[str, Any]]
    history_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    backend_type: str | None = None
    units: dict[str, str] = field(default_factory=dict)
    raw_output: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: int | None = None
    trace_id: str | None = None
    is_mock: bool = False
    software: str | None = None
    software_version: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SIMULATION_STATUSES:
            raise ValueError(f"unsupported simulation status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimulationHistoryEvent:
    history_id: str
    task_id: str
    job_id: str | None
    event_type: str
    actor: str
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "SIMULATION_STATUSES",
    "SIMULATION_STATUS_FAILED",
    "SIMULATION_STATUS_MISSING_PARAMS",
    "SIMULATION_STATUS_SUCCESS",
    "SIMULATION_STATUS_TIMEOUT",
    "SIMULATION_STATUS_UNAVAILABLE",
    "SimulationAdapterResult",
    "SimulationHistoryEvent",
    "SimulationResultEnvelope",
    "SimulationRunRequest",
    "SimulationToolSpec",
]
