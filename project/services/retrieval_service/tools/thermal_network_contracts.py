from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ThermalResistanceElement:
    element_id: str
    name: str | None = None
    element_type: str = "explicit"
    resistance_k_per_w: float | None = None
    thickness_m: float | None = None
    thermal_conductivity_w_mk: float | None = None
    area_m2: float | None = None
    heat_transfer_coefficient_w_m2k: float | None = None
    flow_dependent: bool = False
    source: dict[str, Any] | None = None
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThermalNetworkNode:
    node_id: str
    name: str | None = None
    temperature_c: float | None = None
    node_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThermalNetwork:
    network_id: str
    topology: str
    heat_load_w: float | None = None
    reference_temperature_c: float | None = None
    allowable_junction_temperature_c: float | None = None
    elements: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    connections: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.topology not in {"series", "parallel", "mixed", "unknown"}:
            raise ValueError(f"unsupported thermal-network topology: {self.topology}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThermalNetworkSolveResult:
    status: str
    topology: str
    total_resistance_k_per_w: float | None = None
    heat_load_w: float | None = None
    reference_temperature_c: float | None = None
    junction_temperature_c: float | None = None
    allowable_total_resistance_k_per_w: float | None = None
    margin_c: float | None = None
    elements: list[dict[str, Any]] = field(default_factory=list)
    node_temperatures: list[dict[str, Any]] = field(default_factory=list)
    bottlenecks: list[dict[str, Any]] = field(default_factory=list)
    thermal_path_graph: dict[str, Any] | None = None
    formula: str = ""
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    partial_result: bool = False
    incomplete_network: bool = False
    known_resistance_subtotal_k_per_w: float | None = None
    known_temperature_rise_c: float | None = None
    known_elements: list[dict[str, Any]] = field(default_factory=list)
    missing_elements: list[str] = field(default_factory=list)
    completeness_ratio: float | None = None
    cfd_executed: bool = False
    source: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "engineering_formula",
            "name": "One-dimensional steady thermal-resistance network estimate",
        }
    )
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"success", "partial_result", "missing_params", "unsupported", "failed"}:
            raise ValueError(f"unsupported thermal-network status: {self.status}")
        if self.topology not in {"series", "parallel", "mixed", "unknown"}:
            raise ValueError(f"unsupported thermal-network topology: {self.topology}")
        if self.cfd_executed:
            raise ValueError("thermal-network estimation cannot execute CFD")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PartialThermalNetworkResult:
    generated: bool = True
    status: str = "partial_result"
    partial_result: bool = True
    incomplete_network: bool = True
    known_resistance_subtotal_k_per_w: float | None = None
    known_temperature_rise_c: float | None = None
    known_elements: list[dict[str, Any]] = field(default_factory=list)
    missing_elements: list[str] = field(default_factory=list)
    node_temperatures: list[dict[str, Any]] = field(default_factory=list)
    bottlenecks: list[dict[str, Any]] = field(default_factory=list)
    thermal_path_graph: dict[str, Any] | None = None
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)
    junction_temperature_c: float | None = None
    margin_c: float | None = None
    cfd_executed: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"partial_result", "missing_params"}:
            raise ValueError(f"unsupported partial thermal-network status: {self.status}")
        if not self.partial_result or not self.incomplete_network:
            raise ValueError("partial thermal-network result must remain incomplete")
        if self.junction_temperature_c is not None or self.margin_c is not None:
            raise ValueError("partial thermal-network result cannot expose a complete junction temperature or margin")
        if self.cfd_executed:
            raise ValueError("partial thermal-network result cannot execute CFD")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThermalSensitivityPlan:
    generated: bool
    status: str
    base_metric: str | None = None
    target_metric: str | None = None
    base_junction_temperature_c: float | None = None
    what_if_junction_temperature_c: float | None = None
    delta_temperature_c: float | None = None
    parameters: list[dict[str, Any]] = field(default_factory=list)
    perturbations: list[dict[str, Any]] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cfd_executed: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"ready", "computed", "missing_params", "unsupported"}:
            raise ValueError(f"unsupported thermal-sensitivity status: {self.status}")
        if self.cfd_executed:
            raise ValueError("thermal sensitivity preparation cannot execute CFD")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ThermalNetwork",
    "ThermalNetworkNode",
    "PartialThermalNetworkResult",
    "ThermalNetworkSolveResult",
    "ThermalResistanceElement",
    "ThermalSensitivityPlan",
]
