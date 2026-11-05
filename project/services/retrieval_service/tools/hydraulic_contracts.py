from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


HYDRAULIC_STATUSES = {"success", "missing_params", "missing_data", "unsupported", "failed"}
FLOW_REGIMES = {"laminar", "transitional", "turbulent", "unknown"}


@dataclass(frozen=True)
class HydraulicCalculationResult:
    status: str
    pressure_drop_pa: float | None = None
    pressure_drop_kpa: float | None = None
    required_head_m: float | None = None
    flow_rate_m3_s: float | None = None
    flow_rate_lpm: float | None = None
    velocity_m_s: float | None = None
    reynolds_number: float | None = None
    friction_factor: float | None = None
    flow_regime: str = "unknown"
    major_loss_pa: float | None = None
    minor_loss_pa: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    formula: str = ""
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in HYDRAULIC_STATUSES:
            raise ValueError(f"unsupported hydraulic status: {self.status}")
        if self.flow_regime not in FLOW_REGIMES:
            raise ValueError(f"unsupported flow regime: {self.flow_regime}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PumpSelectionChecklistItem:
    item_id: str
    name: str
    status: str
    detail: str
    required: bool

    def __post_init__(self) -> None:
        if self.status not in {"ok", "missing", "warning", "not_applicable"}:
            raise ValueError(f"unsupported checklist status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PumpSelectionPreparationResult:
    generated: bool
    status: str
    required_flow_rate_lpm: float | None
    required_head_m: float | None
    required_pressure_drop_kpa: float | None
    safety_factor: float | None
    recommended_selection_margin: str | None
    selection_checklist: list[dict[str, Any]] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    not_selected_reason: str = "Pump model selection requires verified vendor pump curves and system constraints."
    pump_model_selected: bool = False
    pump_curve_used: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"ready_for_vendor_selection", "missing_params", "insufficient_curve_data"}:
            raise ValueError(f"unsupported pump preparation status: {self.status}")
        if self.pump_model_selected:
            raise ValueError("this preparation contract cannot select a pump model")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "FLOW_REGIMES",
    "HYDRAULIC_STATUSES",
    "HydraulicCalculationResult",
    "PumpSelectionChecklistItem",
    "PumpSelectionPreparationResult",
]
