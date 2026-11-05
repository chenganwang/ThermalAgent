from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .contracts import DemoQAEvaluationResult


SCORING_WEIGHTS = {
    "top_level_contract_ok": 10,
    "task_type_ok": 10,
    "tool_selection_ok": 15,
    "metadata_contract_ok": 20,
    "forbidden_claims_ok": 15,
    "cards_ok": 10,
    "self_critique_ok": 5,
    "multi_agent_ok": 5,
    "json_serializable_ok": 5,
    "retrieval_count_ok": 5,
}


def score_evaluation_result(result: DemoQAEvaluationResult) -> float:
    return float(sum(weight for field, weight in SCORING_WEIGHTS.items() if bool(getattr(result, field, False))))


def _rate(results: list[DemoQAEvaluationResult], field: str) -> float:
    if not results:
        return 0.0
    return round(sum(1 for result in results if bool(getattr(result, field, False))) / len(results), 6)


def task_type_accuracy(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "task_type_ok")


def tool_selection_accuracy(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "tool_selection_ok")


def metadata_path_pass_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "metadata_contract_ok")


def card_generation_pass_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "cards_ok")


def missing_params_correctness(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "missing_params_ok")


def forbidden_claims_pass_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "forbidden_claims_ok")


def self_critique_presence_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "self_critique_ok")


def multi_agent_trace_presence_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "multi_agent_ok")


def top_level_contract_pass_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "top_level_contract_ok")


def retrieval_count_consistency_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "retrieval_count_ok")


def json_serializable_rate(results: list[DemoQAEvaluationResult]) -> float:
    return _rate(results, "json_serializable_ok")


def category_pass_rate(results: list[DemoQAEvaluationResult]) -> dict[str, float]:
    return {name: values["pass_rate"] for name, values in build_category_scores(results).items()}


def overall_score(results: list[DemoQAEvaluationResult]) -> float:
    if not results:
        return 0.0
    return round(sum(result.score for result in results) / len(results), 4)


def build_category_scores(results: Iterable[DemoQAEvaluationResult]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[DemoQAEvaluationResult]] = defaultdict(list)
    for result in results:
        grouped[result.category].append(result)
    output: dict[str, dict[str, float | int]] = {}
    for category in sorted(grouped):
        values = grouped[category]
        passed = sum(1 for result in values if result.passed)
        output[category] = {
            "total": len(values),
            "passed": passed,
            "pass_rate": round(passed / len(values), 6),
            "average_score": round(sum(result.score for result in values) / len(values), 4),
        }
    return output


def build_metric_scores(results: list[DemoQAEvaluationResult]) -> dict[str, float]:
    return {
        "task_type_accuracy": task_type_accuracy(results),
        "tool_selection_accuracy": tool_selection_accuracy(results),
        "metadata_path_pass_rate": metadata_path_pass_rate(results),
        "card_generation_pass_rate": card_generation_pass_rate(results),
        "missing_params_correctness": missing_params_correctness(results),
        "forbidden_claims_pass_rate": forbidden_claims_pass_rate(results),
        "self_critique_presence_rate": self_critique_presence_rate(results),
        "multi_agent_trace_presence_rate": multi_agent_trace_presence_rate(results),
        "top_level_contract_pass_rate": top_level_contract_pass_rate(results),
        "retrieval_count_consistency_rate": retrieval_count_consistency_rate(results),
        "json_serializable_rate": json_serializable_rate(results),
        "overall_score": overall_score(results),
    }


__all__ = [
    "SCORING_WEIGHTS", "build_category_scores", "build_metric_scores", "card_generation_pass_rate",
    "category_pass_rate", "forbidden_claims_pass_rate", "json_serializable_rate",
    "metadata_path_pass_rate", "missing_params_correctness", "multi_agent_trace_presence_rate",
    "overall_score", "retrieval_count_consistency_rate", "score_evaluation_result",
    "self_critique_presence_rate", "task_type_accuracy", "tool_selection_accuracy",
    "top_level_contract_pass_rate",
]
