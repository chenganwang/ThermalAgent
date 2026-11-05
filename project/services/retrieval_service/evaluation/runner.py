from __future__ import annotations

import json
from typing import Any

from ..demo_cases.frontend_cards import build_frontend_metadata_cards
from ..demo_cases.runner import build_demo_agent
from ..demo_cases.validator import (
    collect_text_matches,
    validate_expected_tools,
    validate_forbidden_claims,
    validate_metadata_paths,
    validate_response_top_level,
)
from .contracts import DemoQAEvaluationResult, DemoQAItem, DemoQASummary
from .metrics import build_category_scores, build_metric_scores, overall_score, score_evaluation_result


def _collect_statuses(value: Any, output: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"status", "tool_status", "network_status", "thermal_network_status"} and item is not None:
                output.add(str(item))
            _collect_statuses(item, output)
    elif isinstance(value, list):
        for item in value:
            _collect_statuses(item, output)


def _safe_response_summary(response: dict[str, Any], visible_cards: list[str]) -> dict[str, Any]:
    metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
    status: dict[str, dict[str, Any]] = {}
    for name in (
        "calculation", "property_lookup", "hydraulics", "pump_selection", "flow_distribution",
        "hydraulic_network", "thermal_network", "thermal_path", "sensitivity", "report",
        "simulation", "self_critique", "multi_agent",
    ):
        block = metadata.get(name)
        if isinstance(block, dict):
            status[name] = {
                key: block.get(key)
                for key in (
                    "used_calculation", "used_property_lookup", "used_hydraulic_calculation",
                    "generated", "enabled", "status", "tool_status", "tool_name", "mode",
                    "pump_model_selected", "pump_curve_used", "cfd_executed",
                )
                if key in block
            }
    task = response.get("task") if isinstance(response.get("task"), dict) else {}
    return {
        "task_type": response.get("task_type"),
        "candidate_tools": list(task.get("candidate_tools") or []),
        "retrieval_count": response.get("retrieval_count"),
        "source_count": len(response.get("sources") or []) if isinstance(response.get("sources"), list) else 0,
        "visible_cards": list(visible_cards),
        "metadata_status": status,
    }


def _status_matches_expected(expected_status: str | None, statuses: set[str], metadata: dict[str, Any]) -> bool:
    if expected_status is None or expected_status in statuses:
        return True
    if expected_status != "missing_params":
        return False
    thermal = metadata.get("thermal_network")
    return bool(
        isinstance(thermal, dict)
        and thermal.get("status") == "partial_result"
        and thermal.get("partial_result") is True
        and thermal.get("incomplete_network") is True
        and list(thermal.get("missing_inputs") or [])
        and thermal.get("junction_temperature_c") is None
    )


def run_demoqa_item(item: DemoQAItem, agent: Any | None = None) -> DemoQAEvaluationResult:
    failures: list[str] = []
    warnings: list[str] = []
    try:
        response = (agent or build_demo_agent()).answer(
            item.query,
            session_id=f"demoqa-{item.case_id}",
            top_k=1,
        )
        top = validate_response_top_level(response)
        failures.extend(top.errors)
        sources = response.get("sources") if isinstance(response.get("sources"), list) else []
        retrieval_count_ok = isinstance(response.get("retrieval_count"), int) and response.get("retrieval_count") == len(sources)
        try:
            json.dumps(response, ensure_ascii=False)
            json_ok = True
        except (TypeError, ValueError):
            json_ok = False
            failures.append("response_not_json_serializable")

        task_type_ok = item.expected_task_type is None or response.get("task_type") == item.expected_task_type
        if not task_type_ok:
            failures.append(f"task_type_mismatch:expected={item.expected_task_type},actual={response.get('task_type')}")

        tools = validate_expected_tools(response, item.expected_tools)
        failures.extend(f"missing_tool:{name}" for name in tools.missing)

        metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
        paths = validate_metadata_paths(metadata, item.expected_metadata_paths)
        failures.extend(f"missing_metadata_path:{path}" for path in paths.missing)

        statuses: set[str] = set()
        _collect_statuses(metadata, statuses)
        status_ok = _status_matches_expected(item.expected_status, statuses, metadata)
        if not status_ok:
            failures.append(f"status_mismatch:expected={item.expected_status},observed={sorted(statuses)}")

        warning_matches = collect_text_matches(response, item.required_warnings)
        if warning_matches.missing:
            warnings.extend(f"required_warning_missing:{value}" for value in warning_matches.missing)
            failures.extend(warnings)

        forbidden = validate_forbidden_claims(response, item.forbidden_claims)
        failures.extend(forbidden.errors)

        cards = build_frontend_metadata_cards(response)
        visible_cards = [str(card.get("card_id")) for card in cards if card.get("visible")]
        missing_cards = [card_id for card_id in item.expected_cards if card_id not in visible_cards]
        failures.extend(f"missing_card:{card_id}" for card_id in missing_cards)

        critique = metadata.get("self_critique")
        self_critique_ok = isinstance(critique, dict) and bool(critique.get("enabled"))
        if not self_critique_ok:
            failures.append("self_critique_missing")
        multi = metadata.get("multi_agent")
        multi_agent_ok = (
            isinstance(multi, dict)
            and bool(multi.get("enabled"))
            and isinstance(multi.get("worker_trace"), list)
        )
        if not multi_agent_ok:
            failures.append("multi_agent_trace_missing")

        result = DemoQAEvaluationResult(
            case_id=item.case_id,
            category=item.category,
            task_type_ok=task_type_ok,
            tool_selection_ok=tools.valid,
            metadata_contract_ok=paths.valid and status_ok and not warning_matches.missing,
            missing_params_ok=status_ok,
            forbidden_claims_ok=forbidden.valid,
            cards_ok=not missing_cards,
            self_critique_ok=self_critique_ok,
            multi_agent_ok=multi_agent_ok,
            top_level_contract_ok=top.valid,
            retrieval_count_ok=retrieval_count_ok,
            json_serializable_ok=json_ok,
            failures=failures,
            warnings=warnings,
            response_summary=_safe_response_summary(response, visible_cards),
        )
        result.score = score_evaluation_result(result)
        result.passed = not failures
        return result
    except Exception as exc:
        return DemoQAEvaluationResult(
            case_id=item.case_id,
            category=item.category,
            failures=[f"runner_error:{exc.__class__.__name__}:{str(exc)[:240]}"],
        )


def run_demoqa_dataset(items: list[DemoQAItem], agent: Any | None = None) -> list[DemoQAEvaluationResult]:
    active_agent = agent or build_demo_agent()
    return [run_demoqa_item(item, agent=active_agent) for item in items]


def summarize_results(results: list[DemoQAEvaluationResult]) -> DemoQASummary:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    return DemoQASummary(
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=round(passed / total, 6) if total else 0.0,
        average_score=overall_score(results),
        category_scores=build_category_scores(results),
        metric_scores=build_metric_scores(results),
        failure_cases=[result.case_id for result in results if not result.passed],
        warnings=[warning for result in results for warning in result.warnings],
    )


__all__ = ["run_demoqa_dataset", "run_demoqa_item", "summarize_results"]
