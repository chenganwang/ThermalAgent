from __future__ import annotations

from dataclasses import replace
from threading import RLock

from .simulation_mode_contracts import SimulationModeState, SimulationPlan


class SimulationSessionStore:
    """Process-local simulation plans; no database or cross-process guarantee."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._plans: dict[str, SimulationPlan] = {}
        self._states: dict[str, SimulationModeState] = {}

    def save_plan(self, session_id: str, plan: SimulationPlan) -> SimulationModeState:
        with self._lock:
            self._plans[session_id] = plan
            state = SimulationModeState(
                enabled=True,
                state="pending_confirmation" if plan.can_execute_now else ("incomplete" if plan.missing_inputs else "blocked"),
                plan_id=plan.plan_id,
                plan_version=plan.version,
                requires_confirmation=plan.requires_confirmation,
                pending_confirmation=plan.requires_confirmation and plan.can_execute_now,
                confirm_allowed=plan.requires_confirmation and plan.can_execute_now,
                confirmed=False,
                executed=False,
                cancelled=False,
                warnings=list(plan.risk_warnings),
            )
            self._states[session_id] = state
            return replace(state)

    def get_plan(self, session_id: str) -> SimulationPlan | None:
        with self._lock:
            return self._plans.get(session_id)

    def get_state(self, session_id: str) -> SimulationModeState:
        with self._lock:
            state = self._states.get(session_id)
            return replace(state) if state is not None else SimulationModeState(enabled=False, pending_confirmation=False)

    def confirm(self, session_id: str, plan_id: str | None, version: int | None = None) -> SimulationModeState:
        with self._lock:
            plan = self._plans.get(session_id)
            state = self._states.get(session_id)
            if plan is None or state is None:
                return self._error("SIMULATION_PLAN_NOT_FOUND", "No pending simulation plan exists.")
            if plan_id != plan.plan_id or (version is not None and version != plan.version):
                return self._error("SIMULATION_PLAN_MISMATCH", "Confirmation does not match the current plan.")
            if state.cancelled:
                return self._error("SIMULATION_PLAN_CANCELLED", "The simulation plan has been cancelled.")
            if state.executed:
                return self._error("SIMULATION_PLAN_ALREADY_EXECUTED", "The simulation plan has already completed.")
            if not plan.can_execute_now or not state.confirm_allowed:
                return replace(state, confirmed=False, pending_confirmation=False, confirm_allowed=False, errors=[{
                    "code": plan.execution_block_reason or "SIMULATION_EXECUTION_NOT_ALLOWED",
                    "message": "The plan is incomplete, invalid, or blocked; execution is not allowed.",
                }])
            state.state = "executing"
            state.confirmed = True
            state.pending_confirmation = False
            state.confirm_allowed = False
            return replace(state)

    def cancel(self, session_id: str, plan_id: str | None = None) -> SimulationModeState:
        with self._lock:
            plan = self._plans.get(session_id)
            state = self._states.get(session_id)
            if plan is None or state is None:
                return self._error("SIMULATION_PLAN_NOT_FOUND", "No pending simulation plan exists.")
            if plan_id is not None and plan_id != plan.plan_id:
                return self._error("SIMULATION_PLAN_MISMATCH", "Cancellation does not match the current plan.")
            state.state = "cancelled"
            state.cancelled = True
            state.confirmed = False
            state.pending_confirmation = False
            state.confirm_allowed = False
            return replace(state)

    def mark_executed(self, session_id: str, *, succeeded: bool) -> SimulationModeState:
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return self._error("SIMULATION_PLAN_NOT_FOUND", "No pending simulation plan exists.")
            state.executed = succeeded
            state.state = "completed" if succeeded else "failed"
            return replace(state)

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._plans.pop(session_id, None)
            self._states.pop(session_id, None)

    @staticmethod
    def _error(code: str, message: str) -> SimulationModeState:
        return SimulationModeState(
            enabled=True,
            state="failed",
            pending_confirmation=False,
            errors=[{"code": code, "message": message}],
        )


__all__ = ["SimulationSessionStore"]
