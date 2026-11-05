from __future__ import annotations

from pathlib import Path
import json
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.task.task_understanding_service import understand_task


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "to_dict"):
        value = result.to_dict()
        if isinstance(value, dict):
            return value
    raise AssertionError(f"task result is not dict-like: {result!r}")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _task(query: str) -> dict[str, Any]:
    return _as_dict(understand_task(query))


def test_concept_explanation() -> None:
    task = _task("什么是冷板液冷？")
    _assert(task["task_type"] in {"concept", "concept_explanation", "retrieval", "general_qa"}, f"unexpected task: {task}")
    _assert(task["needs_calculation"] is False, f"concept should not need calculation: {task}")


def test_liquid_flow_calculation() -> None:
    task = _task("800W 热负荷，水，允许温升 5K，需要多少 L/min 流量？")
    _assert(task["needs_calculation"] is True, f"flow query should need calculation: {task}")
    _assert("liquid_flow_rate_required" in task.get("candidate_tools", []), f"missing flow tool: {task}")


def test_junction_temperature_calculation() -> None:
    task = _task("芯片功耗 800W，环境温度 30℃，总热阻 0.08 K/W，结温是多少？")
    _assert(task["needs_calculation"] is True, f"junction query should need calculation: {task}")
    _assert("junction_temperature_estimate" in task.get("candidate_tools", []), f"missing junction tool: {task}")


def test_ashrae_range_lookup_not_calculation() -> None:
    task = _task("ASHRAE A1 推荐干球温度范围是多少？")
    _assert(task["needs_calculation"] is False, f"ASHRAE range lookup should not need calculation: {task}")
    _assert(task["task_type"] != "calculation", f"ASHRAE range lookup should not be calculation: {task}")


def test_ocp_water_temperature_lookup_not_calculation() -> None:
    task = _task("OCP W27 供水温度范围是多少？")
    _assert(task["needs_calculation"] is False, f"OCP range lookup should not need calculation: {task}")
    _assert(task["task_type"] != "calculation", f"OCP range lookup should not be calculation: {task}")


def test_property_lookup() -> None:
    task = _task("40% EGW 在 25℃ 下 cp 是多少？")
    _assert(task["task_type"] == "property_lookup" or task.get("is_property_lookup") is True, f"missing property lookup: {task}")
    _assert(task["needs_calculation"] is False, f"property lookup should not need calculation: {task}")
    _assert("liquid_flow_rate_required" not in task.get("candidate_tools", []), f"property lookup should not route to flow tool: {task}")


def test_visualization_request() -> None:
    task = _task("请画一个芯片到 TIM、冷板、冷却液和 CDU 的散热路径图。")
    _assert(task.get("needs_visualization") is True, f"visualization flag missing: {task}")
    _assert(task["task_type"] in {"visualization", "analysis", "design_advice", "general_qa"}, f"unexpected visualization task: {task}")


def test_report_request() -> None:
    task = _task("请生成 800W 芯片冷板液冷分析报告。")
    _assert(task.get("needs_report") is True, f"report flag missing: {task}")
    _assert(task["task_type"] in {"report", "analysis", "design_advice", "general_qa"}, f"unexpected report task: {task}")


def test_comparison_request() -> None:
    task = _task("比较风冷和冷板液冷在 AI 服务器中的适用场景。")
    _assert(task.get("needs_comparison") is True, f"comparison flag missing: {task}")
    _assert(task["task_type"] in {"comparison", "analysis", "design_advice"}, f"unexpected comparison task: {task}")


def test_simulation_request() -> None:
    task = _task("我上传了 cabinet_model.step，请做机柜液冷仿真准备。")
    _assert(task.get("needs_simulation") is True, f"simulation flag missing: {task}")
    _assert(task["task_type"] in {"simulation", "analysis", "design_advice", "general_qa"}, f"unexpected simulation task: {task}")


def test_irrelevant_or_analogy() -> None:
    task = _task("冷板液冷系统和食堂排队有什么关系？")
    _assert(
        task["task_type"] == "irrelevant_or_analogy" or task.get("is_irrelevant_or_analogy") is True,
        f"analogy query should be flagged: {task}",
    )


def main() -> None:
    tests = [
        test_concept_explanation,
        test_liquid_flow_calculation,
        test_junction_temperature_calculation,
        test_ashrae_range_lookup_not_calculation,
        test_ocp_water_temperature_lookup_not_calculation,
        test_property_lookup,
        test_visualization_request,
        test_report_request,
        test_comparison_request,
        test_simulation_request,
        test_irrelevant_or_analogy,
    ]
    for test in tests:
        test()
    print(json.dumps({"status": "ok", "task_understanding_service_cases": len(tests)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
