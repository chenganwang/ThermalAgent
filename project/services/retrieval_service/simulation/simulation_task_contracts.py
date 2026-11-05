from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


READINESS_LEVELS = {"not_ready", "partially_ready", "ready_for_preprocessing", "ready_for_solver_setup"}


@dataclass(frozen=True)
class SimulationTask:
    task_id: str
    task_type: str
    model_file: dict[str, Any]
    geometry: dict[str, Any]
    materials: dict[str, Any]
    heat_sources: list[dict[str, Any]]
    boundary_conditions: dict[str, Any]
    coolant_loop: dict[str, Any]
    solver_goal: dict[str, Any]
    required_inputs: list[str]
    missing_inputs: list[str]
    readiness_level: str
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.readiness_level not in READINESS_LEVELS:
            raise ValueError(f"unsupported readiness_level: {self.readiness_level}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimulationTaskBuilderResult:
    generated: bool
    simulation_ready: bool
    readiness_level: str
    task: dict[str, Any]
    checklist: list[dict[str, Any]]
    missing_inputs: list[str]
    warnings: list[str]
    not_run_reason: str
    cfd_executed: bool = False

    def __post_init__(self) -> None:
        if self.readiness_level not in READINESS_LEVELS:
            raise ValueError(f"unsupported readiness_level: {self.readiness_level}")
        if self.cfd_executed:
            raise ValueError("Simulation Task Builder cannot execute CFD")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["READINESS_LEVELS", "SimulationTask", "SimulationTaskBuilderResult"]
