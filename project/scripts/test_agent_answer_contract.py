from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.agent_orchestrator import ThermalAgent
from services.retrieval_service.config import load_config
from services.retrieval_service.conversation_memory import ConversationMemory
from services.retrieval_service.simulation.model_file_registry import (
    clear_registered_model_files,
    register_model_file,
)


TOP_LEVEL_KEYS = {
    "answer",
    "query",
    "task_type",
    "retrieval_count",
    "task",
    "rewrite",
    "sources",
    "session_id",
    "metadata",
}

METADATA_KEYS = {
    "calculation",
    "knowledge",
    "analysis_mode",
    "analysis_workflow",
    "visualization",
    "simulation",
    "solution",
    "comparison",
    "report",
    "self_critique",
}

CALCULATION_KEYS = {
    "used_calculation",
    "tool_name",
    "tool_status",
    "tool_inputs",
    "tool_result",
    "tool_formula",
    "tool_steps",
    "tool_warnings",
    "missing_parameters",
    "assumptions",
}

FORBIDDEN_SIMULATION_RESULT_KEYS = {
    "cfd_result",
    "cfd_results",
    "simulation_result",
    "simulation_results",
    "solver_output",
    "solver_results",
    "temperature_field",
    "velocity_field",
    "pressure_field",
    "converged",
}

EMPTY_RESULT_VALUES = (None, False, "", [], {})
SIMULATION_OVERCLAIM_PHRASES = (
    "真实 CFD 结果已完成",
    "CFD 求解已完成",
    "真实仿真结果",
    "simulation completed",
    "cfd completed",
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _fake_retriever(_cfg, _query: str, _top_k: int):
    return [], 0, None


def _agent() -> ThermalAgent:
    return ThermalAgent(
        cfg=load_config(),
        memory=ConversationMemory(backend="memory"),
        retriever_func=_fake_retriever,
        enable_llm=False,
    )


def _answer(
    query: str,
    *,
    session_id: str = "agent-answer-contract",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _agent().answer(query, session_id=session_id, top_k=1, request_options=options or {})


@contextmanager
def _env(**updates: str | None):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _require_keys(mapping: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in mapping)
    _assert(not missing, f"{label} missing keys {missing}: {mapping}")


def _require_top_level_contract(response: dict[str, Any], query: str) -> None:
    _require_keys(response, TOP_LEVEL_KEYS, "agent answer")
    _assert(isinstance(response["answer"], str), f"answer must be str: {response}")
    _assert(isinstance(response["query"], str), f"query must be str: {response}")
    _assert(response["query"] == query, f"query should preserve old behavior: {response}")
    _assert(isinstance(response["task_type"], str), f"task_type must be str: {response}")
    _assert(isinstance(response["retrieval_count"], int), f"retrieval_count must be int: {response}")
    _assert(isinstance(response["task"], dict), f"task must be dict: {response}")
    _assert(isinstance(response["rewrite"], dict), f"rewrite must be dict: {response}")
    _assert(isinstance(response["sources"], list), f"sources must be list: {response}")
    _assert(response["session_id"] is None or isinstance(response["session_id"], str), f"bad session_id: {response}")
    _assert(isinstance(response["metadata"], dict), f"metadata must be dict: {response}")
    json.dumps(response, ensure_ascii=False)


def _require_metadata_contract(metadata: dict[str, Any]) -> None:
    _require_keys(metadata, METADATA_KEYS, "metadata")
    _require_keys(metadata["calculation"], CALCULATION_KEYS, "metadata.calculation")
    _assert(isinstance(metadata["knowledge"], dict), f"knowledge must be dict: {metadata}")
    _assert(isinstance(metadata["analysis_mode"], dict), f"analysis_mode must be dict: {metadata}")
    _assert(isinstance(metadata["analysis_workflow"], dict), f"analysis_workflow must be dict: {metadata}")
    _assert(isinstance(metadata["visualization"], dict), f"visualization must be dict: {metadata}")
    _assert(isinstance(metadata["simulation"], dict), f"simulation must be dict: {metadata}")
    _assert(isinstance(metadata["solution"], dict), f"solution must be dict: {metadata}")
    _assert(isinstance(metadata["comparison"], dict), f"comparison must be dict: {metadata}")
    _assert(isinstance(metadata["report"], dict), f"report must be dict: {metadata}")
    _assert(isinstance(metadata["self_critique"], dict), f"self_critique must be dict: {metadata}")


def _require_disabled_or_generated_flags(metadata: dict[str, Any]) -> None:
    _assert("generated" in metadata["visualization"], f"visualization.generated missing: {metadata['visualization']}")
    _assert("enabled" in metadata["simulation"], f"simulation.enabled missing: {metadata['simulation']}")
    _assert("generated" in metadata["solution"], f"solution.generated missing: {metadata['solution']}")
    _assert("generated" in metadata["comparison"], f"comparison.generated missing: {metadata['comparison']}")
    _assert("generated" in metadata["report"], f"report.generated missing: {metadata['report']}")


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_walk_keys(item))
    return keys


def _walk_items(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from _walk_items(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_items(item)


def _require_no_real_cfd_result_payload(simulation: dict[str, Any]) -> None:
    for key, value in _walk_items(simulation):
        if key in FORBIDDEN_SIMULATION_RESULT_KEYS:
            _assert(
                value in EMPTY_RESULT_VALUES,
                f"simulation must not expose real CFD payload for {key}: {value!r}",
            )
        if key == "will_run_cfd":
            _assert(value is False, f"contract fixture must not schedule real CFD: {simulation}")
    dumped = json.dumps(simulation, ensure_ascii=False)
    for phrase in SIMULATION_OVERCLAIM_PHRASES:
        _assert(phrase.lower() not in dumped.lower(), f"simulation overclaims real CFD output: {phrase}")


def test_concept_answer_keeps_top_level_and_metadata_contract() -> None:
    query = "什么是冷板液冷？"
    response = _answer(query, session_id="contract-concept")
    _require_top_level_contract(response, query)
    _require_metadata_contract(response["metadata"])
    _require_disabled_or_generated_flags(response["metadata"])
    calculation = response["metadata"]["calculation"]
    _assert(calculation["used_calculation"] is False, f"concept should not calculate: {calculation}")
    _assert(calculation["tool_result"] == {}, f"concept tool_result should be empty: {calculation}")


def test_calculation_answer_keeps_tool_result_contract() -> None:
    query = "800W 热负荷，水，允许温升 5K，需要多少 L/min 流量？"
    response = _answer(query, session_id="contract-calculation")
    _require_top_level_contract(response, query)
    metadata = response["metadata"]
    _require_metadata_contract(metadata)
    calculation = metadata["calculation"]
    _assert(calculation["used_calculation"] is True, f"calculation should be used: {calculation}")
    _assert(calculation["tool_name"] == "liquid_flow_rate_required", f"tool changed: {calculation}")
    _assert(calculation["tool_status"] == "ok", f"tool status changed: {calculation}")
    _assert(isinstance(calculation["tool_result"], dict) and calculation["tool_result"], f"tool_result missing: {calculation}")
    _assert("volume_flow_L_min" in calculation["tool_result"], f"legacy tool_result value missing: {calculation}")


def test_report_answer_exposes_analysis_report_metadata() -> None:
    query = "请生成 800W 芯片冷板液冷分析报告。"
    response = _answer(
        query,
        session_id="contract-report",
        options={"analysis_report_mode": True, "requested_outputs": ["report"]},
    )
    _require_top_level_contract(response, query)
    metadata = response["metadata"]
    _require_metadata_contract(metadata)
    _assert(metadata["analysis_mode"]["enabled"] is True, f"analysis mode should be enabled: {metadata['analysis_mode']}")
    _assert(metadata["analysis_workflow"]["enabled"] is True, f"analysis workflow should be enabled: {metadata['analysis_workflow']}")
    report = metadata["report"]
    _assert(report["generated"] is True, f"report should be generated: {report}")
    _assert(isinstance(report.get("content"), str) and report["content"].strip(), f"report content missing: {report}")
    _assert("sections" in report and isinstance(report["sections"], list), f"report sections missing: {report}")
    _assert("quality" in report or "render_hints" in report, f"report quality/render_hints missing: {report}")


def test_visualization_answer_exposes_graph_contract() -> None:
    query = "请画一个芯片到 TIM、冷板、冷却液和 CDU 的散热路径图。"
    response = _answer(
        query,
        session_id="contract-visualization",
        options={"analysis_report_mode": True, "requested_outputs": ["visualization"]},
    )
    _require_top_level_contract(response, query)
    visualization = response["metadata"]["visualization"]
    _assert(visualization["generated"] is True, f"visualization should be generated: {visualization}")
    _assert("graph_type" in visualization, f"graph_type missing: {visualization}")
    _assert("graph" in visualization and isinstance(visualization["graph"], dict), f"graph missing: {visualization}")
    graph = visualization["graph"]
    _assert(isinstance(graph.get("nodes"), list) and graph["nodes"], f"graph.nodes missing: {graph}")
    _assert(isinstance(graph.get("edges"), list) and graph["edges"], f"graph.edges missing: {graph}")
    _assert("generic_template" in visualization or "generic_template" in graph, f"generic_template missing: {visualization}")
    _assert(visualization.get("simulation_based") is False, f"generic graph must not be simulation based: {visualization}")


def test_simulation_readiness_does_not_expose_real_cfd_result() -> None:
    clear_registered_model_files()
    register_model_file("model-001", "cabinet_model.step", "机柜模型")
    query = "我上传了 cabinet_model.step，请做机柜液冷仿真准备。"
    response = _answer(
        query,
        session_id="contract-simulation",
        options={
            "analysis_report_mode": True,
            "requested_outputs": ["simulation"],
            "uploaded_model_file_id": "model-001",
            "uploaded_model_filename": "cabinet_model.step",
        },
    )
    _require_top_level_contract(response, query)
    simulation = response["metadata"]["simulation"]
    _assert(simulation["enabled"] is True, f"simulation should be enabled: {simulation}")
    _assert(simulation["simulation_ready"] is False, f"simulation should remain readiness-only: {simulation}")
    _assert("readiness" in simulation and isinstance(simulation["readiness"], dict), f"readiness missing: {simulation}")
    _assert("task" in simulation and isinstance(simulation["task"], dict), f"task missing: {simulation}")
    _require_no_real_cfd_result_payload(simulation)


def test_property_lookup_does_not_default_egw_to_water_calculation() -> None:
    query = "40% EGW 在 25℃ 下 cp 是多少？"
    response = _answer(query, session_id="contract-property-lookup")
    _require_top_level_contract(response, query)
    metadata = response["metadata"]
    calculation = metadata["calculation"]
    _assert(calculation["used_calculation"] is False, f"EGW property lookup must not calculate: {calculation}")
    _assert(calculation["tool_result"] == {}, f"EGW property lookup must not produce water tool_result: {calculation}")
    _assert(calculation["tool_name"] != "liquid_flow_rate_required", f"EGW property lookup misrouted: {calculation}")
    dumped = json.dumps(response, ensure_ascii=False)
    _assert("volume_flow_L_min" not in dumped, "EGW property lookup should not produce a water flow-rate result")


def test_self_critique_contract_is_visible() -> None:
    query = "CDU 是什么？"
    response = _answer(query, session_id="contract-self-critique")
    critique = response["metadata"]["self_critique"]
    for key in ("enabled", "passed", "severity", "issues", "repair_action", "route"):
        _assert(key in critique, f"self_critique missing key {key}: {critique}")
    _assert(isinstance(critique["issues"], list), f"self_critique.issues must be list: {critique}")


def test_task_model_assist_shadow_is_optional_and_never_routes() -> None:
    query = "800W 热负荷，水，允许温升 5K，需要多少 L/min 流量？"
    with _env(TASK_MODEL_ASSIST_SHADOW_ENABLED="false", TASK_MODEL_ASSIST_ENABLED="false"):
        baseline = _answer(query, session_id="contract-shadow-baseline")
        shadowed = _answer(
            query,
            session_id="contract-shadow-enabled",
            options={"task_model_assist_shadow": True},
        )
    _assert(
        "task_model_assist" not in baseline["metadata"]
        or baseline["metadata"]["task_model_assist"].get("enabled") is False,
        f"shadow should be optional by default: {baseline['metadata'].get('task_model_assist')}",
    )
    shadow = shadowed["metadata"].get("task_model_assist")
    _assert(isinstance(shadow, dict), f"shadow metadata missing when requested: {shadowed['metadata']}")
    _assert(shadow["used_for_routing"] is False, f"shadow must never route: {shadow}")
    _assert(shadowed["task_type"] == baseline["task_type"], "shadow must not affect task_type")
    calculations = []
    run_ids = []
    for response, expected_session in ((baseline, "contract-shadow-baseline"), (shadowed, "contract-shadow-enabled")):
        calculation = response["metadata"]["calculation"]
        run = response["metadata"]["engineering_run"]
        run_id = run.get("run_id")
        _assert(isinstance(run_id, str) and bool(run_id), "each calculation must own a recorded Run ID")
        _assert(calculation["raw"].get("run_id") == run_id, "calculation must reference its own engineering Run")
        _assert(response["session_id"] == expected_session, "shadow must preserve the requesting session")
        run_ids.append(run_id)
        # Only this per-execution identity is expected to differ. Keep all
        # inputs, results, fingerprints, validation and warnings in the equality.
        calculations.append({**calculation, "raw": {key: value for key, value in calculation["raw"].items() if key != "run_id"}})
    _assert(run_ids[0] != run_ids[1], "independent baseline and shadow calls must create distinct Runs")
    _assert(calculations[1] == calculations[0], "shadow must not affect calculation business metadata")
    _assert(shadowed["answer"] == baseline["answer"], "shadow must not affect answer")


def main() -> None:
    tests = [
        test_concept_answer_keeps_top_level_and_metadata_contract,
        test_calculation_answer_keeps_tool_result_contract,
        test_report_answer_exposes_analysis_report_metadata,
        test_visualization_answer_exposes_graph_contract,
        test_simulation_readiness_does_not_expose_real_cfd_result,
        test_property_lookup_does_not_default_egw_to_water_calculation,
        test_self_critique_contract_is_visible,
        test_task_model_assist_shadow_is_optional_and_never_routes,
    ]
    for test in tests:
        test()
    print(json.dumps({"status": "ok", "agent_answer_contract_cases": len(tests)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
