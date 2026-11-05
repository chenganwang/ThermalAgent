from __future__ import annotations

from pathlib import Path
import json
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.agent_orchestrator import ThermalAgent
from services.retrieval_service.config import load_config
from services.retrieval_service.conversation_memory import ConversationMemory
from services.retrieval_service.query_rewriter import rewrite_query
from services.retrieval_service.task_understanding import (
    TaskUnderstandingResult,
    classify_task_type,
    extract_entities,
    is_calculation_request,
    normalize_query,
    understand_task,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "to_dict"):
        mapped = result.to_dict()
        if isinstance(mapped, dict):
            return mapped
    raise AssertionError(f"result is not dict-like: {result!r}")


def _fake_retriever(cfg, query: str, top_k: int):
    return [], 0, None


def test_legacy_understand_task_dict_contract() -> None:
    result = understand_task("800W 热负荷，水，允许温升 5K，需要多少 L/min 流量？")
    data = _as_dict(result)
    _assert(isinstance(data, dict), f"legacy understand_task should be dict-like: {result}")
    for key in (
        "task_type",
        "domain",
        "entities",
        "intent",
        "needs_retrieval",
        "needs_calculation",
        "needs_visualization",
        "confidence",
        "original_query",
        "normalized_query",
        "warnings",
    ):
        _assert(key in data, f"legacy field missing {key}: {data}")
    for key in (
        "candidate_tools",
        "properties",
        "needs_report",
        "needs_comparison",
        "needs_simulation",
        "is_property_lookup",
        "is_irrelevant_or_analogy",
        "raw_signals",
    ):
        _assert(key in data, f"new compatible field missing {key}: {data}")


def test_legacy_public_functions_still_exist() -> None:
    _assert(normalize_query("冷板，液冷？") == "冷板,液冷?", "normalize_query compatibility changed")
    _assert("冷板" in extract_entities("冷板液冷"), "extract_entities compatibility changed")
    task_type, confidence = classify_task_type("CDU 是什么？")
    _assert(isinstance(task_type, str) and isinstance(confidence, float), "classify_task_type return changed")
    _assert(is_calculation_request("800W 热负荷，水，允许温升 5K，需要多少 L/min 流量？") is True, "calculation detection changed")
    _assert(TaskUnderstandingResult is not None, "TaskUnderstandingResult import missing")


def test_query_rewriter_accepts_task_result() -> None:
    task = understand_task("40% EGW 在 25℃ 下 cp 是多少？")
    rewrite = rewrite_query("40% EGW 在 25℃ 下 cp 是多少？", task)
    data = rewrite.to_dict()
    _assert(data["rewritten_query"], f"rewrite should produce query: {data}")
    _assert("property" in json.dumps(data, ensure_ascii=False).lower() or "物性" in json.dumps(data, ensure_ascii=False), f"property rewrite missing: {data}")


def test_agent_orchestrator_still_calls_task_understanding() -> None:
    agent = ThermalAgent(
        cfg=load_config(),
        memory=ConversationMemory(backend="memory"),
        retriever_func=_fake_retriever,
        enable_llm=False,
    )
    result = agent.answer("CDU 是什么？", session_id="task-regression", top_k=1)
    _assert("answer" in result and "task" in result and "metadata" in result, f"agent response shape changed: {result}")
    _assert(result["metadata"]["calculation"]["used_calculation"] is False, f"ordinary query calculation metadata changed: {result['metadata']}")


def main() -> None:
    tests = [
        test_legacy_understand_task_dict_contract,
        test_legacy_public_functions_still_exist,
        test_query_rewriter_accepts_task_result,
        test_agent_orchestrator_still_calls_task_understanding,
    ]
    for test in tests:
        test()
    print(json.dumps({"status": "ok", "task_understanding_regression_cases": len(tests)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
