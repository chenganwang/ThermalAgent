from __future__ import annotations

from .regression_contracts import RegressionTestItem


def _test(
    test_id: str,
    command: str,
    suite: str,
    *,
    timeout: int = 120,
    slow: bool = False,
    required: bool = True,
    reason: str = "",
    tags: list[str] | None = None,
) -> RegressionTestItem:
    return RegressionTestItem(
        test_id=test_id, command=command, suite=suite, required=required,
        timeout_seconds=timeout, slow=slow, reason=reason, tags=list(tags or []),
    )


QUICK = [
    _test("compileall", "python -m compileall -q services scripts cli.py", "quick_regression", timeout=60, tags=["syntax"]),
    _test("agent_answer_contract", "python scripts\\test_agent_answer_contract.py", "quick_regression", tags=["api"]),
    _test("agent_smoke", "python scripts\\smoke_test_agent.py", "quick_regression", tags=["smoke"]),
    _test("task_service", "python scripts\\test_task_understanding_service.py", "quick_regression", tags=["task"]),
    _test("task_regression", "python scripts\\test_task_understanding_regression.py", "quick_regression", tags=["task"]),
    _test("demoqa_smoke", "python scripts\\test_demoqa_evaluation_smoke.py", "quick_regression", tags=["evaluation"]),
    _test("scenario_quick", "python scripts\\test_scenario_regression_quick.py", "quick_regression", tags=["scenario"]),
]

FEATURE = [
    _test("demoqa_contracts", "python scripts\\test_demoqa_contracts.py", "feature_regression", tags=["evaluation"]),
    _test("demoqa_dataset", "python scripts\\test_demoqa_dataset_integrity.py", "feature_regression", tags=["evaluation"]),
    _test("demoqa_metrics", "python scripts\\test_demoqa_metrics.py", "feature_regression", tags=["evaluation"]),
    _test("demoqa_runner", "python scripts\\test_demoqa_runner.py", "feature_regression", tags=["evaluation"]),
    _test("demoqa_report", "python scripts\\test_demoqa_report_generation.py", "feature_regression", tags=["evaluation"]),
    _test("demoqa_failure_analysis", "python scripts\\test_demoqa_failure_analysis.py", "feature_regression", required=False, reason="expected legacy test is absent", tags=["evaluation", "optional"]),
    _test("demoqa_forbidden", "python scripts\\test_demoqa_forbidden_claims.py", "feature_regression", tags=["safety"]),
    _test("demoqa_metadata", "python scripts\\test_demoqa_metadata_coverage.py", "feature_regression", tags=["metadata"]),
    _test("demoqa_full_test", "python scripts\\test_demoqa_full_evaluation.py", "feature_regression", required=False, reason="expected legacy test is absent", tags=["evaluation", "optional"]),
    _test("demoqa_limit10", "python scripts\\evaluate_thermalagent_demoqa_50.py --limit 10", "feature_regression", tags=["evaluation"]),
]

FULL_EXTRA = [
    *[_test(f"demo_{name}", f"python scripts\\{name}.py", "full_regression", tags=["demo"]) for name in (
        "test_demo_case_contracts", "test_demo_case_registry", "test_demo_case_validator", "test_demo_case_runner",
        "test_frontend_metadata_cards_contract", "test_frontend_metadata_cards_fixtures",
        "test_demo_case_agent_integration", "test_scenario_regression_quick",
    )],
    *[_test(f"agent_{name}", f"python scripts\\{name}.py", "full_regression", tags=["agent"]) for name in (
        "test_agent_metadata_builder", "test_agent_response_builder", "test_agent_pipeline_contracts",
        "test_analysis_metadata_contract", "test_self_critique_agent_contract",
        "test_multi_agent_metadata_contract", "test_multi_agent_agent_integration",
    )],
    _test("hydraulics_integration", "python scripts\\test_hydraulics_agent_integration.py", "full_regression", tags=["hydraulics"]),
    _test("hydraulic_network_integration", "python scripts\\test_hydraulic_network_agent_integration.py", "full_regression", tags=["hydraulics"]),
    _test("thermal_network_integration", "python scripts\\test_thermal_network_agent_integration.py", "full_regression", tags=["thermal"]),
    _test("report_integration", "python scripts\\test_report_template_agent_integration.py", "full_regression", tags=["report"]),
    _test("simulation_integration", "python scripts\\test_simulation_task_builder_agent_integration.py", "full_regression", tags=["simulation"]),
    _test("task_eval66", "python scripts\\evaluate_task_understanding.py", "full_regression", tags=["task"]),
    _test("demoqa_full", "python scripts\\evaluate_thermalagent_demoqa_50.py", "full_regression", tags=["evaluation"]),
]


def _clone_for_suite(items: list[RegressionTestItem], suite: str) -> list[RegressionTestItem]:
    return [
        RegressionTestItem(
            test_id=item.test_id, command=item.command, suite=suite, required=item.required,
            timeout_seconds=item.timeout_seconds, slow=item.slow, reason=item.reason, tags=list(item.tags),
        )
        for item in items
    ]


SLOW = [
    _test(
        "agent_calculation_chain", "python scripts\\test_agent_calculation_chain.py", "slow_regression",
        timeout=900, slow=True, reason="explicitly classified slow; never included by default", tags=["slow", "calculation"],
    )
]

SUITES = {
    "quick_regression": QUICK,
    "feature_regression": FEATURE,
    "full_regression": _clone_for_suite(QUICK + FEATURE, "full_regression") + FULL_EXTRA,
    "slow_regression": SLOW,
}


def get_suite(name: str) -> list[RegressionTestItem]:
    if name not in SUITES:
        raise ValueError(f"unknown regression suite: {name}")
    return list(SUITES[name])


__all__ = ["FEATURE", "FULL_EXTRA", "QUICK", "SLOW", "SUITES", "get_suite"]
