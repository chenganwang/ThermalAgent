from __future__ import annotations

from pathlib import Path
import json
import math
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.agent_orchestrator import ThermalAgent
from services.retrieval_service.config import AppConfig, load_config
from services.retrieval_service.conversation_memory import ConversationMemory
from services.retrieval_service.retriever import Hit


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    cfg = load_config()
    retrieval_calls: list[dict[str, Any]] = []

    def unavailable_retriever(_cfg: AppConfig, query: str, top_k: int) -> tuple[list[Hit], int, Any]:
        retrieval_calls.append({"query": query, "top_k": top_k})
        raise RuntimeError("smoke test: retrieval backend unavailable")

    memory = ConversationMemory(backend="memory")
    agent = ThermalAgent(cfg=cfg, memory=memory, retriever_func=unavailable_retriever, enable_llm=False)

    first = agent.answer("液冷冷板有什么作用？", session_id="smoke-session", top_k=3)
    _assert(isinstance(first.get("answer"), str) and first["answer"], "agent answer must return non-empty answer")
    _assert("task" in first and isinstance(first["task"], dict), "agent answer must include task")
    _assert("rewrite" in first and isinstance(first["rewrite"], dict), "agent answer must include rewrite")
    _assert("sources" in first and isinstance(first["sources"], list), "agent answer must include sources")
    _assert(first["metadata"]["retrieval_count"] == 0, "empty/unavailable DB path should return zero retrieval count")
    _assert(first["metadata"]["retrieval_error"], "unavailable retrieval should be reported without traceback")
    _assert(retrieval_calls, "agent must attempt a retrieval call")

    second = agent.answer("它和风冷比有什么优势？", session_id="smoke-session", top_k=3)
    _assert(second["metadata"]["used_memory"] is True, "second turn should use memory context")
    resolved = second["rewrite"]["original_query"]
    _assert("液冷" in resolved or "冷板" in resolved, "memory should resolve pronoun references")

    calculation = agent.answer("壁厚5mm，导热系数16W/(mK)，面积0.002m²，两侧温差60K，计算平壁导热热流。",
                               session_id="engineering-smoke")
    execution = calculation["metadata"].get("engineering_run") or {}
    _assert(execution.get("status") == "incomplete", "unavailable retrieval must keep the execution evidence incomplete")
    _assert(execution["steps"][1]["status"] == "completed", "calculation must still complete without retrieval")
    _assert(calculation["metadata"]["calculation"]["tool_result"]["heat_rate_W"] == 384.0,
            "plane wall smoke must preserve the physical reference result")
    _assert(execution.get("validation", {}).get("passed") is True, "engineering execution must carry physical evidence")

    from services.retrieval_service import v11_api_server

    routes = {getattr(route, "path", "") for route in v11_api_server.app.routes}
    for path in {"/health", "/agent/answer", "/agent/analyze", "/agent/memory/reset", "/engineering/tasks/continue"}:
        _assert(path in routes, f"FastAPI route missing: {path}")

    from services.engineering_service.task_contracts import EngineeringTaskRequest
    from services.engineering_service.task_continuation import _delta
    frozen = EngineeringTaskRequest.model_validate({"query": "工程导热计算", "reference_solver": {
        "area_m2": .01, "left_temperature_k": 350., "right_temperature_k": 300.,
        "layers": [{"thickness_m": .002, "conductivity_w_mk": 200.}]},
        "design_criteria": {"max_heat_rate_abs_w": 100.}}).model_dump(mode="json")
    delta = _delta({"request": frozen}, "保留原任务，把上限改成200W重新评估。")
    _assert(delta["changes"][0]["after"] == 200., "continuation must resolve a typed design change")
    _assert(frozen["design_criteria"]["max_heat_rate_abs_w"] == 100., "continuation must preserve parent input")

    # Keep the reported regression in the ordinary smoke path too: the scalar
    # first-match calculator must never consume only the first layer again.
    multiline = ("两层平壁稳态导热：\n面积 A = 0.01 m²\n热端 = 360 K\n冷端 = 290 K\n"
                 "第一层：\nL1 = 0.002 m\nk1 = 200 W/(m·K)\n"
                 "第二层：\nL2 = 0.003 m\nk2 = 1 W/(m·K)\n设计指标：\n热流绝对值不得超过100 W")
    wall = agent.answer(multiline, session_id="multilayer-smoke")["metadata"]
    values = wall["calculation"]["tool_result"]
    _assert(abs(values["equivalent_resistance"] - .301) < 1e-12, "multilayer smoke must retain both layers")
    _assert(abs(values["heat_rate"] - 70 / .301) < 1e-7, "changed boundary temperatures must reach the solver")
    _assert(wall["engineering_run"]["validation"]["passed"] and not wall["design_review"]["passed"],
            "physics PASS cannot erase design limit FAIL")
    _assert(wall["engineering_run"]["calculation_fingerprint"] == wall["reference_solver"]["input_fingerprint"],
            "the returned numerical receipt must belong to this Run")

    # Exercise the persisted flow -> pressure -> conservation path using only a
    # temporary engineering store and the explicit unavailable retrieval fixture.
    from services.engineering_service.store import EngineeringStore
    from services.engineering_service.tasks import TaskService
    with TemporaryDirectory(prefix="thermal-liquid-smoke-") as temporary:
        store = EngineeringStore(Path(temporary) / "engineering.sqlite3")
        service = TaskService(store, SimpleNamespace(cfg=load_config(Path(temporary)),
                              retriever_func=unavailable_retriever), autostart=False)
        queued = service.submit({"query": "液冷流量与压降守恒检查", "session_id": "small-flow-smoke",
            "liquid_cooling": {"heat_load_w": .004, "coolant_delta_t_k": 5., "specific_heat_j_kgk": 4180.,
                "density_kg_m3": 1000., "dynamic_viscosity_pa_s": .001, "hydraulic_diameter_m": .008,
                "length_m": 2., "minor_loss_coefficient": 2.}})
        service.run_next()
        liquid = service.get(queued["task_id"])
        _assert(liquid["status"] == "incomplete", "missing retrieval must keep the liquid task incomplete")
        steps = {step["step_id"]: step for step in liquid["steps"]}
        _assert(all(steps[key]["status"] == "completed" for key in ("flow", "pressure", "validation")),
                "small valid quantities must complete both actual tools and the physical check")
        flow = steps["flow"]["outputs"]
        pressure = steps["pressure"]["outputs"]
        _assert(math.isclose(flow["mass_flow_kg_s"] * 4180 * 5, .004, rel_tol=1e-12, abs_tol=0),
                "machine-readable mass flow must preserve the independent energy equation")
        _assert(math.isclose(pressure["flow_rate_m3_s"] * 1000 * 4180 * 5, .004, rel_tol=1e-12, abs_tol=0),
                "the pressure tool must consume the unrounded flow result")
        _assert(pressure["pressure_drop_pa"] > 0 and pressure["required_head_m"] > 0,
                "small positive hydraulic quantities must not be rounded to zero")
        _assert(liquid["validation"]["passed"] and liquid["validation"]["energy_relative_error"] < 1e-12,
                "small-flow conservation must pass without weakening its tolerance")
        _assert(store.list_runs()["total"] == 2, "both actual tools must have persisted Run receipts")

    report = {
        "status": "ok",
        "checks": [
            "ThermalAgent import",
            "answer structure",
            "task understanding",
            "query rewriting",
            "retrieval call attempted",
            "sources field stable",
            "no-DB graceful fallback",
            "two-turn memory reference resolution",
            "FastAPI agent routes import",
            "session-bound engineering continuation route import",
            "typed engineering continuation without mutating parent inputs",
            "planned deterministic calculation and physics receipt",
            "multiline two-layer inputs, independent design review and result fingerprint",
            "small-flow persisted flow-pressure chain and independent energy conservation",
        ],
        "first_task_type": first["task"].get("task_type"),
        "second_resolved_query": resolved,
        "retrieval_calls": retrieval_calls,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
