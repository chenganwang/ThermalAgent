from __future__ import annotations

from typing import Any

from ..agent_orchestrator import ThermalAgent
from ..config import load_config
from ..conversation_memory import ConversationMemory
from .contracts import DemoCase, DemoCaseRunResult
from .frontend_cards import build_frontend_metadata_cards
from .validator import (
    collect_text_matches,
    validate_expected_tools,
    validate_forbidden_claims,
    validate_metadata_paths,
    validate_response_top_level,
)


def _empty_retriever(_cfg: Any, _query: str, _top_k: int):
    return [], 0, None


def build_demo_agent() -> ThermalAgent:
    """Build a deterministic, offline agent for demo regression."""

    return ThermalAgent(
        cfg=load_config(),
        memory=ConversationMemory(backend="memory"),
        retriever_func=_empty_retriever,
        enable_llm=False,
    )


def _response_summary(response: dict[str, Any]) -> dict[str, Any]:
    metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
    status: dict[str, Any] = {}
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
                    "generated", "enabled", "status", "tool_status", "tool_name",
                    "pump_model_selected", "pump_curve_used", "cfd_executed",
                )
                if key in block
            }
    return {
        "task_type": response.get("task_type"),
        "retrieval_count": response.get("retrieval_count"),
        "source_count": len(response.get("sources") or []) if isinstance(response.get("sources"), list) else 0,
        "metadata_status": status,
    }


def run_demo_case(case: DemoCase, agent: Any | None = None) -> DemoCaseRunResult:
    failures: list[str] = []
    warnings: list[str] = []
    try:
        active_agent = agent or build_demo_agent()
        response = active_agent.answer(case.query, session_id=f"demo-{case.case_id}", top_k=1)
        top = validate_response_top_level(response)
        failures.extend(top.errors)
        metadata = response.get("metadata") if isinstance(response, dict) else {}
        paths = validate_metadata_paths(metadata, case.expected_metadata_paths)
        failures.extend(f"missing_metadata_path:{path}" for path in paths.missing)
        tools = validate_expected_tools(response, case.expected_tools)
        failures.extend(f"missing_tool:{name}" for name in tools.missing)
        forbidden = validate_forbidden_claims(response, case.should_not_include)
        failures.extend(forbidden.errors)
        warning_matches = collect_text_matches(response, case.expected_warnings)
        warnings.extend(f"expected_warning_not_observed:{item}" for item in warning_matches.missing)
        failures.extend(warnings)
        cards = build_frontend_metadata_cards(response)
        visible_cards = [str(card["card_id"]) for card in cards if card.get("visible")]
        missing_cards = [card_id for card_id in case.expected_cards if card_id not in visible_cards]
        failures.extend(f"missing_card:{card_id}" for card_id in missing_cards)
        if case.expected_task_type and response.get("task_type") != case.expected_task_type:
            failures.append(
                f"task_type_mismatch:expected={case.expected_task_type},actual={response.get('task_type')}"
            )
        return DemoCaseRunResult(
            case_id=case.case_id,
            passed=not failures,
            query=case.query,
            top_level_contract_ok=top.valid,
            expected_tools_found=tools.found,
            missing_tools=tools.missing,
            metadata_paths_found=paths.found,
            missing_metadata_paths=paths.missing,
            cards_generated=visible_cards,
            warnings=warnings,
            failures=failures,
            response_summary=_response_summary(response),
        )
    except Exception as exc:
        failures.append(f"runner_error:{exc.__class__.__name__}:{str(exc)[:240]}")
        return DemoCaseRunResult(
            case_id=case.case_id,
            passed=False,
            query=case.query,
            top_level_contract_ok=False,
            failures=failures,
        )


def run_demo_cases(cases: list[DemoCase], agent: Any | None = None) -> list[DemoCaseRunResult]:
    active_agent = agent or build_demo_agent()
    return [run_demo_case(case, agent=active_agent) for case in cases]


__all__ = ["build_demo_agent", "run_demo_case", "run_demo_cases"]
