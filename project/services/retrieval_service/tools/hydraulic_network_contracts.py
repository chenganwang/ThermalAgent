from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class HydraulicBranch:
    branch_id: str
    name: str | None = None
    topology: str = "unknown"
    resistance_coefficient: float | None = None
    resistance_exponent: float | None = None
    pressure_drop_pa: float | None = None
    flow_rate_lpm: float | None = None
    flow_rate_m3_s: float | None = None
    identical_group_id: str | None = None
    geometry: dict[str, Any] = field(default_factory=dict)
    loss_coefficients: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class HydraulicNetwork:
    network_id: str
    topology: str
    total_flow_rate_lpm: float | None = None
    total_flow_rate_m3_s: float | None = None
    common_pressure_drop_pa: float | None = None
    branches: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class FlowDistributionResult:
    status: str
    topology: str
    total_flow_rate_lpm: float | None = None
    total_flow_rate_m3_s: float | None = None
    common_pressure_drop_pa: float | None = None
    total_pressure_drop_pa: float | None = None
    total_pressure_drop_kpa: float | None = None
    branches: list[dict[str, Any]] = field(default_factory=list)
    flow_imbalance_ratio: float | None = None
    formula: str = ""
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    cfd_executed: bool = False
    source: dict[str, Any] = field(default_factory=lambda: {"type": "engineering_formula", "name": "One-dimensional hydraulic network estimate"})
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"success", "missing_params", "unsupported", "failed"}:
            raise ValueError(f"unsupported flow distribution status: {self.status}")
        if self.topology not in {"series", "parallel", "mixed", "unknown"}:
            raise ValueError(f"unsupported topology: {self.topology}")
        if self.cfd_executed:
            raise ValueError("network preparation cannot execute CFD")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


__all__ = ["FlowDistributionResult", "HydraulicBranch", "HydraulicNetwork"]
