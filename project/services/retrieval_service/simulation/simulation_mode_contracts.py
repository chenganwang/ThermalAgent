from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SimulationPlan:
    plan_id: str
    user_goal: str
    simulation_type: str
    objective: str | None = None
    user_question: str | None = None
    scenario_id: str | None = None
    scenario_confidence: float = 0.0
    model_id: str | None = None
    selected_model_id: str | None = None
    selected_model_name: str | None = None
    selection_reason: str | None = None
    candidate_models: list[dict[str, Any]] = field(default_factory=list)
    model_selection_confidence: float = 0.0
    model_version: str | None = None
    model_source: str = "catalog"
    generated_model_id: str | None = None
    generated_model_revision: int | None = None
    generated_model_status: str | None = None
    generated_model_summary: dict[str, Any] = field(default_factory=dict)
    model_file_required: bool = False
    model_file_path: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    parameter_sources: dict[str, str] = field(default_factory=dict)
    input_normalizations: dict[str, dict[str, Any]] = field(default_factory=dict)
    input_errors: list[dict[str, Any]] = field(default_factory=list)
    input_conflicts: list[dict[str, Any]] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    boundary_conditions: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    cooling_loop: dict[str, Any] = field(default_factory=dict)
    solver_backend: str = "unavailable"
    solver: dict[str, Any] = field(default_factory=dict)
    matlab_entrypoint: str | None = None
    execution_steps: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = True
    execution_allowed: bool = False
    execution_block_reason: str | None = None
    status: str = "draft"
    version: int = 1
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def can_execute_now(self) -> bool:
        """Input/capability readiness; explicit confirmation is still required."""
        return self.execution_allowed and not self.missing_inputs and not self.input_errors and not self.input_conflicts

    @property
    def missing_parameters(self) -> list[str]:
        return list(self.missing_inputs)

    @property
    def checklist(self) -> list[str]:
        return [f"provide:{name}" for name in self.missing_inputs]

    @property
    def warnings(self) -> list[str]:
        return list(self.risk_warnings)

    @property
    def not_executable_reason(self) -> str | None:
        return self.execution_block_reason

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_model_id"] = self.selected_model_id or self.model_id
        payload["generated"] = True
        payload["objective"] = self.objective or self.user_goal
        payload["user_question"] = self.user_question or self.user_goal
        payload["missing_parameters"] = self.missing_parameters
        payload["checklist"] = self.checklist
        payload["warnings"] = self.warnings
        payload["not_executable_reason"] = self.not_executable_reason
        payload["can_execute_now"] = self.can_execute_now
        return payload


@dataclass(slots=True)
class SimulationModeState:
    enabled: bool = False
    state: str = "off"
    plan_id: str | None = None
    plan_version: int | None = None
    requires_confirmation: bool = False
    pending_confirmation: bool = False
    confirm_allowed: bool = False
    confirmed: bool = False
    executed: bool = False
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    persistence: str = "in_memory_process_local"
    ui_actions: list[str] = field(
        default_factory=lambda: ["show_plan", "show_confirm", "show_cancel", "show_status"]
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["button_state"] = {
            "show_plan": self.enabled,
            "show_confirm": self.confirm_allowed and self.pending_confirmation and not self.cancelled and not self.confirmed,
            "show_cancel": bool(self.plan_id) and not self.cancelled and not self.executed,
            "show_status": self.enabled,
        }
        return payload


@dataclass(slots=True)
class SimulationExecutionResult:
    plan_id: str | None = None
    executed: bool = False
    status: str = "not_started"
    solver_backend: str | None = None
    matlab_entrypoint: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    result: dict[str, Any] = field(default_factory=dict)
    result_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    cfd_executed: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["backend"] = self.solver_backend
        return payload


__all__ = ["SimulationExecutionResult", "SimulationModeState", "SimulationPlan", "utc_now_iso"]
