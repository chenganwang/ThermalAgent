from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import Any

from .simulation_confirmation import classify_confirmation
from .simulation_executor import ConfirmedSimulationExecutor
from .simulation_mode_contracts import SimulationExecutionResult, SimulationModeState, SimulationPlan
from .simulation_mode_state import SimulationSessionStore
from .simulation_planner import NaturalLanguageSimulationPlanner


@dataclass(slots=True)
class SimulationModeResponse:
    handled: bool
    answer: str
    metadata: dict[str, Any]


class SimulationModeOrchestrator:
    def __init__(
        self,
        *,
        planner: NaturalLanguageSimulationPlanner | None = None,
        store: SimulationSessionStore | None = None,
        executor: ConfirmedSimulationExecutor | Any | None = None,
    ) -> None:
        self.planner = planner or NaturalLanguageSimulationPlanner()
        self.store = store or SimulationSessionStore()
        self.executor = executor or ConfirmedSimulationExecutor()
        self._executions: dict[str, SimulationExecutionResult] = {}
        self._lock = RLock()

    def handle(self, query: str, session_id: str, options: dict[str, Any] | None = None) -> SimulationModeResponse:
        opts = dict(options or {})
        explicit_action = opts.get("simulation_action")
        action = classify_confirmation(query, str(explicit_action) if explicit_action else None)
        enabled = (
            bool(opts.get("simulation_mode"))
            or action in {"confirm", "cancel", "revise", "status", "plan"}
            or _requests_simulation_mode(query)
        )
        if not enabled:
            return SimulationModeResponse(False, "", {})
        if action == "confirm":
            return self._confirm(session_id, opts.get("simulation_plan_id"))
        if action == "cancel":
            current_plan = self.store.get_plan(session_id)
            state = self.store.cancel(session_id, opts.get("simulation_plan_id"))
            self._release_generated_session(session_id, current_plan)
            return SimulationModeResponse(True, "已取消当前仿真计划；未执行任何求解器。", self._metadata(session_id, state))
        if action == "status":
            state = self.store.get_state(session_id)
            return SimulationModeResponse(True, self._status_answer(state), self._metadata(session_id, state))
        old = self.store.get_plan(session_id)
        old_state = self.store.get_state(session_id)
        revision = action == "revise" or (
            action != "plan" and old is not None and not old_state.cancelled
            and not old_state.confirmed and self.planner.can_revise(old, query)
        )
        if revision and old is not None:
            requested_id = opts.get("simulation_plan_id")
            if requested_id and requested_id != old.plan_id:
                state = replace(old_state, errors=[{"code": "SIMULATION_PLAN_MISMATCH", "message": "Revision does not match the current plan."}])
                return SimulationModeResponse(True, "补参未应用：计划已经更新，请修改当前计划。", self._metadata(session_id, state))
            if old_state.state == "executing":
                return SimulationModeResponse(True, "当前仿真正在执行，暂不能修改。", self._metadata(session_id, old_state))
            if query.strip() in {"修改仿真计划", "修改方案", "重新规划"}:
                return SimulationModeResponse(True, "请直接在对话中补充或修正参数，例如：温差就是60K。", self._metadata(session_id, old_state))
        if action != "plan" and not revision and not self.planner.should_plan(query):
            state = SimulationModeState(enabled=True, state="available")
            return SimulationModeResponse(
                False,
                "",
                {
                    "simulation_mode": state.to_dict(),
                    "simulation_plan": _empty_plan_metadata(),
                    "simulation_execution": SimulationExecutionResult().to_dict(),
                },
            )
        plan = self.planner.revise(old, query) if revision and old is not None else self.planner.plan(query)
        self._apply_runtime_guard(plan)
        state = self.store.save_plan(session_id, plan)
        if old is not None and old.generated_model_id != plan.generated_model_id:
            self._release_generated_session(session_id, old)
        self._register_generated_session(session_id, plan)
        with self._lock:
            self._executions[session_id] = SimulationExecutionResult(plan_id=plan.plan_id)
        return SimulationModeResponse(True, self._plan_answer(plan), self._metadata(session_id, state))

    def _apply_runtime_guard(self, plan: SimulationPlan) -> None:
        if plan.solver_backend != "matlab" or not plan.execution_allowed:
            return
        runtime = getattr(self.executor, "matlab_runtime", None)
        status_method = getattr(runtime, "connection_status", None)
        if not callable(status_method):
            return
        try:
            status = status_method(start=False)
        except Exception:
            plan.execution_allowed = False
            plan.execution_block_reason = "MATLAB_STATUS_CHECK_FAILED"
            plan.status = "blocked"
            plan.risk_warnings.append("MATLAB 连接状态检查失败，不能执行。")
            return
        if not bool(getattr(status, "available", False)):
            error = getattr(status, "engine_error", None) or {}
            plan.execution_allowed = False
            plan.execution_block_reason = str(error.get("code") or "MATLAB_NOT_AVAILABLE")
            plan.status = "blocked"
            plan.risk_warnings.append("MATLAB 当前不可用；计划保留，但确认不会启动求解器。")

    def _confirm(self, session_id: str, requested_plan_id: str | None) -> SimulationModeResponse:
        plan = self.store.get_plan(session_id)
        if plan is None:
            state = self.store.confirm(session_id, requested_plan_id)
            return SimulationModeResponse(True, "没有可确认的仿真计划。", self._metadata(session_id, state))
        if plan.model_source == "generated":
            self.planner.refresh_generated_plan(plan)
            self._apply_runtime_guard(plan)
            self.store.save_plan(session_id, plan)
        plan_id = str(requested_plan_id or plan.plan_id)
        state = self.store.confirm(session_id, plan_id, plan.version)
        if state.errors:
            if plan_id == plan.plan_id and not plan.can_execute_now:
                # Preserve structured capability/input errors without claiming that
                # an incomplete plan was confirmed or invoking any executor.
                with self._lock:
                    self._executions[session_id] = SimulationExecutionResult(
                        plan_id=plan.plan_id, status="blocked", solver_backend=plan.solver_backend,
                        matlab_entrypoint=plan.matlab_entrypoint, errors=list(state.errors),
                    )
            if plan.missing_inputs:
                return SimulationModeResponse(True, "暂不能确认执行，请在对话中补充：" + "、".join(plan.missing_inputs) + "。", self._metadata(session_id, state))
            if plan.input_errors:
                return SimulationModeResponse(True, "暂不能确认执行，参数存在矛盾或无效值，请在对话中修正。", self._metadata(session_id, state))
            if not plan.can_execute_now:
                return SimulationModeResponse(True, f"暂不能确认执行（{plan.execution_block_reason}），未启动求解器。", self._metadata(session_id, state))
            return SimulationModeResponse(True, "确认未通过：计划标识与当前版本不匹配。", self._metadata(session_id, state))
        if not plan.execution_allowed:
            result = SimulationExecutionResult(
                plan_id=plan.plan_id,
                status="blocked",
                solver_backend=plan.solver_backend,
                matlab_entrypoint=plan.matlab_entrypoint,
                warnings=["simulation_execution_not_completed"],
                errors=[
                    {
                        "code": plan.execution_block_reason or "SIMULATION_EXECUTION_NOT_ALLOWED",
                        "message": "The reviewed plan is not executable.",
                    }
                ],
                cfd_executed=False,
            )
        else:
            result = self.executor.execute(plan, confirmed=True)
        with self._lock:
            self._executions[session_id] = result
        state = self.store.mark_executed(session_id, succeeded=result.executed)
        self._release_generated_session(session_id, plan)
        if result.executed:
            answer = f"仿真已执行完成。结果：{result.result}"
        else:
            code = (result.errors[0] if result.errors else {}).get("code", "SIMULATION_EXECUTION_FAILED")
            answer = f"计划已确认，但仿真没有完成（{code}）。"
        return SimulationModeResponse(True, answer, self._metadata(session_id, state))

    def reset(self, session_id: str) -> None:
        plan = self.store.get_plan(session_id)
        self._release_generated_session(session_id, plan)
        self.store.reset(session_id)
        with self._lock:
            self._executions.pop(session_id, None)

    def _register_generated_session(self, session_id: str, plan: SimulationPlan) -> None:
        if plan.model_source != "generated" or not plan.generated_model_id:
            return
        repository = getattr(getattr(self.planner, "generated_model_service", None), "repository", None)
        register = getattr(repository, "register_session_reference", None)
        if not callable(register):
            return
        try:
            register(plan.generated_model_id, session_id)
        except Exception:
            plan.execution_allowed = False
            plan.execution_block_reason = "GENERATED_MODEL_SESSION_REGISTRATION_FAILED"
            plan.status = "blocked"

    def _release_generated_session(self, session_id: str, plan: SimulationPlan | None) -> None:
        if plan is None or plan.model_source != "generated" or not plan.generated_model_id:
            return
        repository = getattr(getattr(self.planner, "generated_model_service", None), "repository", None)
        release = getattr(repository, "release_session_reference", None)
        if callable(release):
            release(plan.generated_model_id, session_id)

    def _metadata(self, session_id: str, state: SimulationModeState) -> dict[str, Any]:
        plan = self.store.get_plan(session_id)
        with self._lock:
            result = self._executions.get(session_id) or SimulationExecutionResult(plan_id=state.plan_id)
        matlab = self._matlab_status()
        return {
            "simulation_mode": state.to_dict(),
            "simulation_plan": plan.to_dict() if plan else _empty_plan_metadata(),
            "matlab": matlab,
            "simulation_execution": result.to_dict(),
            "simulation": {
                "enabled": state.enabled,
                "state": state.state,
                "plan_id": state.plan_id,
                "executed": result.executed,
                "cfd_executed": False,
            },
        }

    def _matlab_status(self) -> dict[str, Any]:
        runtime = getattr(self.executor, "matlab_runtime", None)
        status = getattr(runtime, "connection_status", None)
        if callable(status):
            try:
                return status(start=False).to_dict()
            except Exception:
                pass
        return {
            "configured": False,
            "available": False,
            "connected": False,
            "execution_mode": "unavailable",
            "uses_real_matlab": False,
        }

    @staticmethod
    def _plan_answer(plan: SimulationPlan) -> str:
        if plan.execution_allowed:
            return (
                f"已生成仿真计划 {plan.plan_id}（v{plan.version}）：{plan.scenario_id} / "
                f"{plan.solver_backend}。参数已完整，但尚未执行；请明确确认后才会启动求解器。"
            )
        missing = "、".join(plan.missing_inputs) if plan.missing_inputs else "无"
        reason = plan.execution_block_reason or "SIMULATION_EXECUTION_NOT_ALLOWED"
        return f"已生成仿真准备计划 {plan.plan_id}，当前不可执行（{reason}）。待补参数：{missing}。"

    @staticmethod
    def _status_answer(state: SimulationModeState) -> str:
        if not state.plan_id:
            return "当前会话没有仿真计划。"
        return f"当前仿真计划 {state.plan_id} 状态为 {state.state}。"


__all__ = ["SimulationModeOrchestrator", "SimulationModeResponse"]


def _requests_simulation_mode(query: str) -> bool:
    text = str(query or "").lower()
    return any(
        phrase in text
        for phrase in ("打开仿真模式", "开启仿真模式", "开启仿真模块", "进入仿真分析模式", "simulation mode")
    )


def _empty_plan_metadata() -> dict[str, Any]:
    return {
        "generated": False,
        "plan_id": None,
        "objective": None,
        "user_question": None,
        "simulation_type": None,
        "model_id": None,
        "selected_model_id": None,
        "selected_model_name": None,
        "model_source": "catalog",
        "generated_model_id": None,
        "generated_model_revision": None,
        "generated_model_status": None,
        "generated_model_summary": {},
        "selection_reason": None,
        "candidate_models": [],
        "model_selection_confidence": 0.0,
        "inputs": {},
        "missing_inputs": [],
        "checklist": [],
        "execution_steps": [],
        "expected_outputs": [],
        "matlab_entrypoint": None,
        "can_execute_now": False,
        "not_executable_reason": None,
        "requires_confirmation": True,
    }
