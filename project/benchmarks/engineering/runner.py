"""Run real local task workflows against isolated knowledge and SQLite fixtures."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from .catalog import DATASET_VERSION, FIXTURE_CHUNK_ID, FIXTURE_DOC_ID, FIXTURE_TEXT, FIXTURE_TITLE, load_cases
from .oracles import ORACLE_VERSION, expected_values

RUNNER_VERSION = "engineering-task-benchmark-v1"
NINE_FIELDS = {"answer", "query", "task_type", "retrieval_count", "task", "rewrite", "sources", "session_id", "metadata"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _check(name, passed, actual=None, expected=None):
    return dict(check=name, passed=bool(passed), actual=actual, expected=expected)


def _dimension(checks):
    return {"status": "not_applicable" if not checks else "passed" if all(c["passed"] for c in checks) else "failed", "checks": checks}


def evaluate_case(case, task, initial, safety):
    """Score observed records. Oracle outputs are never sent to the task service."""
    steps = {s["step_id"]: s for s in task.get("steps", [])}
    events = task.get("events", [])
    result = task.get("result") or {}
    variables = [v for v in task.get("variables", []) if v.get("role") == "output"]
    oracle = expected_values(case.oracle, case.oracle_inputs)
    dimensions = {}
    plan = [_check("required_steps", set(case.expected_steps) <= set(steps), list(steps), case.expected_steps),
            _check("plan_saved_before_execution", initial.get("status") == "queued" and all(s.get("status") == "pending" for s in initial.get("steps", [])),
                   initial.get("status"), "queued; every declared step pending")]
    declared = {s["step_id"]: s.get("depends_on", []) for s in initial.get("steps", [])}
    plan.append(_check("dependencies_preserved", declared == {k: s.get("depends_on", []) for k, s in steps.items()}))
    plan.append(_check("event_sequence", [e.get("sequence") for e in events] == list(range(1, len(events) + 1))))
    dimensions["planning_trace"] = _dimension(plan)
    executed = [s for s in steps.values() if s.get("tool_name") and s.get("started_at") and s["step_id"] != "validation"]
    names = list(dict.fromkeys(s["tool_name"] for s in executed))
    tool_checks = [_check("executed_tool_set", set(names) == set(case.expected_tools), names, case.expected_tools),
                   _check("tool_versions_recorded", all(s.get("tool_version") for s in executed))]
    for parent, child in case.expected_dependencies:
        tool_checks.append(_check(f"declared_edge:{parent}->{child}", parent in steps.get(child, {}).get("depends_on", [])))
        starts = [e["sequence"] for e in events if e.get("step_id") == child and e.get("status") == "running"]
        permitted = {"completed", "incomplete", "failed", "blocked", "skipped", "cancelled", "interrupted"} if steps.get(child, {}).get("dependency_policy") == "after_terminal" else {"completed"}
        finishes = [e["sequence"] for e in events if e.get("step_id") == parent and e.get("status") in permitted]
        if starts and case.physics_required:
            tool_checks.append(_check(f"execution_order:{parent}->{child}", bool(finishes) and max(finishes) < min(starts), [finishes, starts]))
    if "flow" in steps and "pressure" in steps and case.physics_required:
        flow = steps["flow"].get("outputs", {}).get("volume_flow_L_min")
        bound = steps["pressure"].get("inputs", {}).get("flow_rate_lpm")
        tool_checks.append(_check("flow_output_bound_to_pressure_input", flow is not None and flow == bound, bound, flow))
    dimensions["tools_dependencies"] = _dimension(tool_checks)
    number_checks = []
    for expectation in case.variables:
        matches = [v for v in variables if v.get("name") == expectation.name and (expectation.step_id is None or v.get("step_id") == expectation.step_id)]
        expected = oracle[expectation.oracle_key]
        numeric = bool(matches) and all(isinstance(v.get("value"), (int, float)) and not isinstance(v["value"], bool) and math.isfinite(v["value"]) and math.isclose(v["value"], expected, rel_tol=expectation.relative_tolerance, abs_tol=expectation.absolute_tolerance) for v in matches)
        number_checks += [_check(f"numeric:{expectation.name}", numeric, [v.get("value") for v in matches], expected),
                          _check(f"unit:{expectation.name}", bool(matches) and all(v.get("unit") == expectation.unit for v in matches), [v.get("unit") for v in matches], expectation.unit),
                          _check(f"origin:{expectation.name}", bool(matches) and all(v.get("source") for v in matches))]
    dimensions["numerics_units"] = _dimension(number_checks)
    physical = []
    if case.physics_required:
        validation = task.get("validation") or {}
        physical += [_check("deterministic_validator_passed", validation.get("passed") is True and validation.get("status") == "passed", validation.get("status"), "passed"),
                     _check("energy_balance_was_checked", validation.get("energy_balance_checked") is True)]
        if case.oracle == "liquid":
            output = steps.get("pressure", {}).get("outputs", {})
            volume = output.get("flow_rate_m3_s")
            recovered = volume * case.oracle_inputs["density_kg_m3"] * case.oracle_inputs["specific_heat_j_kgk"] * case.oracle_inputs["coolant_delta_t_k"] if isinstance(volume, (float, int)) else None
            physical.append(_check("independent_actual_flow_energy_closure", recovered is not None and math.isclose(recovered, case.oracle_inputs["heat_load_w"], rel_tol=1e-5, abs_tol=1e-6), recovered, case.oracle_inputs["heat_load_w"]))
        if case.oracle == "layered_wall":
            reference = result.get("metadata", {}).get("reference_solver") or {}
            points = [point for history in reference.get("histories", []) for point in history.get("points", [])]
            lo, hi = sorted((case.oracle_inputs["left_temperature_k"], case.oracle_inputs["right_temperature_k"]))
            physical += [_check("actual_reference_not_mock_or_cfd", reference.get("reference_executed") is True and reference.get("is_mock") is False and reference.get("cfd_executed") is False),
                         _check("boundary_temperature_bounds", bool(points) and all(lo - 1e-8 <= point[1] <= hi + 1e-8 for point in points))]
    dimensions["physics"] = _dimension(physical)
    sources = result.get("sources") or []
    source_checks = [_check("source_count_contract", result.get("retrieval_count") == len(sources), result.get("retrieval_count"), len(sources))]
    if case.source_required:
        source_checks += [_check("fixture_source_identity", bool(sources) and all(s.get("doc_id") == FIXTURE_DOC_ID and s.get("chunk_id") == FIXTURE_CHUNK_ID for s in sources)),
                          _check("citation_location_and_title", bool(sources) and all(s.get("page_start") == 1 and s.get("page_end") == 2 and "BENCHMARK FIXTURE" in (s.get("title") or "") for s in sources))]
    else:
        source_checks.append(_check("no_fabricated_sources", not sources, sources, []))
    dimensions["source_provenance"] = _dimension(source_checks)
    report_checks = []
    if case.report_required:
        report = result.get("metadata", {}).get("report") or {}
        content = report.get("content") or ""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        report_checks += [_check("report_generated", report.get("generated") is True and bool(content.strip())),
                          _check("task_report_sha256", bool(content) and task.get("report", {}).get("content_sha256") == content_hash, task.get("report", {}).get("content_sha256"), content_hash),
                          _check("report_contains_checked_variables", all(v.name in content for v in case.variables)),
                          _check("stable_response_contract", set(result) == NINE_FIELDS, sorted(result), sorted(NINE_FIELDS))]
        if case.source_required:
            report_checks.append(_check("report_contains_source_identifier", str(FIXTURE_CHUNK_ID) in content))
    dimensions["report_integrity"] = _dimension(report_checks)
    outcome = [_check("outcome", task.get("status") == case.expected_status, task.get("status"), case.expected_status)]
    if case.missing_parameters:
        outcome.append(_check("missing_parameters_explained", set(case.missing_parameters) <= set(task.get("missing_parameters", [])), task.get("missing_parameters"), case.missing_parameters))
        outcome.append(_check("missing_inputs_do_not_create_outputs", not variables))
    if case.design_status:
        review = task.get("design_review") or {}
        checks = review.get("checks") or []
        limit = case.request["design_criteria"]["max_pressure_drop_pa"]
        expected_pressure = oracle["pressure_drop_pa"]
        outcome += [_check("design_status", review.get("status") == case.design_status, review.get("status"), case.design_status),
                    _check("independent_limit_violation", expected_pressure > limit and any(
                        isinstance(c.get("actual"), (int, float)) and math.isclose(c["actual"], expected_pressure, rel_tol=1e-5, abs_tol=1e-6)
                        and c.get("maximum") == limit and c.get("unit") == "Pa" and c.get("source") == "recorded_tool_output"
                        and math.isclose(c.get("margin", 0), limit - c["actual"], rel_tol=1e-5, abs_tol=1e-6) and c["margin"] < 0
                        for c in checks), expected_pressure, f"> {limit} Pa")]
    dimensions["outcome_exceptions_design"] = _dimension(outcome)
    dimensions["execution_safety"] = _dimension([_check(name, count == 0, count, 0) for name, count in safety.items()])
    passed = all(d["status"] != "failed" for d in dimensions.values())
    semantic = dict(status=task.get("status"), tools=names, variables=variables, sources=sources, validation=task.get("validation"), design_review=task.get("design_review"))
    return dict(case_id=case.case_id, title=case.title, passed=passed, observed_status=task.get("status"), dimensions=dimensions,
                input_sha256=digest(case.request), case_sha256=digest(case.model_dump(mode="json")), oracle_values=oracle,
                semantic_output_sha256=digest(semantic), task_id=task.get("task_id"), planner_version=task.get("planner_version"),
                tool_versions={s["tool_name"]: s.get("tool_version") for s in executed})


def execute_case(case):
    # Imports are deliberately inside the offline execution entry, after the CLI
    # has set numerical thread limits. No API lifespan or production .env loads.
    from services.engineering_service.store import EngineeringStore
    from services.engineering_service.tasks import TaskService
    from services.retrieval_service.config import load_config
    with TemporaryDirectory(prefix="thermal-agent-benchmark-") as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch.dict(os.environ, {"CFD_MODE": "mock", "AGENT_ENABLE_LLM": "false", "TASK_MODEL_ASSIST_ENABLED": "false", "TASK_MODEL_ASSIST_SHADOW_ENABLED": "false", "ENGINEERING_STORE_PATH": str(root / "records.sqlite3")}))
        guards = {"business_db_calls": stack.enter_context(patch("services.retrieval_service.db.DB.create", side_effect=AssertionError("Benchmark forbids business DB"))),
                  "external_process_calls": stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("Benchmark forbids subprocesses"))),
                  "network_connect_calls": stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("Offline benchmark forbids network"))),
                  "model_classifier_calls": stack.enter_context(patch("services.retrieval_service.task.model_assist.classify_task_with_model", side_effect=AssertionError("Benchmark forbids LLM evaluation")))}
        stack.enter_context(patch("services.retrieval_service.answering.source_formatter.document_title_map", return_value={FIXTURE_DOC_ID: {"title": FIXTURE_TITLE, "doc_type": "synthetic_benchmark_fixture"}}))
        hit = SimpleNamespace(doc_id=FIXTURE_DOC_ID, chunk_id=FIXTURE_CHUNK_ID, chunk_index=0, score=.95, page_start=1, page_end=2,
                              section_path="Benchmark fixture > Steady ideal models", chunk_type="text", text=FIXTURE_TEXT, expanded_text=FIXTURE_TEXT, meta_json=None)
        retrieval_calls = []
        def retrieve(_cfg, query, top_k):
            retrieval_calls.append({"query": query, "top_k": top_k})
            return ([hit] if case.knowledge == "fixture" else []), 1, None
        store = EngineeringStore(root / "records.sqlite3")
        service = TaskService(store, SimpleNamespace(cfg=load_config(root), retriever_func=retrieve), autostart=False)
        accepted = service.submit(deepcopy(case.request))
        initial = deepcopy(service.get(accepted["task_id"]))
        service.run_next()
        task = service.get(accepted["task_id"])
        safety = {name: guard.call_count for name, guard in guards.items()}
        evaluated = evaluate_case(case, task, initial, safety)
        evaluated["retrieval_calls"] = len(retrieval_calls)
        runs = store.list_runs()
        evaluated["persistent_runs"] = runs["total"]
        evaluated["model_versions"] = sorted({run["model_version"] for run in runs["runs"]})
        return evaluated, {"initial": initial, "task": task, "retrieval": retrieval_calls, "runs": runs["runs"]}


def run_benchmark(output_root, case_ids=None):
    cases = load_cases()
    if case_ids:
        unknown = set(case_ids) - {c.case_id for c in cases}
        if unknown:
            raise ValueError("Unknown benchmark case IDs: " + ", ".join(sorted(unknown)))
        cases = [c for c in cases if c.case_id in case_ids]
    output = Path(output_root) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    catalog = [c.model_dump(mode="json") for c in cases]
    (output / "catalog.snapshot.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    results = []
    for case in cases:
        start = time.perf_counter()
        try:
            result, receipt = execute_case(case)
            (output / f"{case.case_id}.receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        except Exception as exc:
            # Do not leak environment values, connection strings or private paths.
            result = dict(case_id=case.case_id, title=case.title, passed=False, observed_status="benchmark_execution_error",
                          dimensions={"execution_safety": _dimension([_check("execution_completed", False, type(exc).__name__, "real task receipt")])},
                          input_sha256=digest(case.request), case_sha256=digest(case.model_dump(mode="json")))
        result["duration_seconds"] = round(time.perf_counter() - start, 4)
        results.append(result)
    names = sorted({name for result in results for name in result["dimensions"]})
    summary = {name: {state: sum(r["dimensions"].get(name, {}).get("status") == state for r in results) for state in ("passed", "failed", "not_applicable")} for name in names}
    project = Path(__file__).resolve().parents[2]
    implementation_files = ["services/engineering_service/tasks.py", "services/engineering_service/task_workflow.py",
                            "services/engineering_service/reference_workflow.py", "services/engineering_service/design_review.py",
                            "services/retrieval_service/tools/thermal_calculators.py", "services/retrieval_service/tools/hydraulic_calculators.py",
                            "services/simulation_service/reference/service.py", "services/physics_service/validator.py",
                            "benchmarks/engineering/catalog.py", "benchmarks/engineering/oracles.py", "benchmarks/engineering/runner.py"]
    report = dict(schema_version="1.0", runner_version=RUNNER_VERSION, dataset_version=DATASET_VERSION, oracle_version=ORACLE_VERSION,
                  created_at=datetime.now(timezone.utc).isoformat(), python_version=platform.python_version(), mode="offline-controlled-knowledge-fixture",
                  limitations=["Fixture citation/provenance acceptance only; this is not production RAG retrieval quality, recall or answer grounding evaluation.",
                               "Analytic oracles verify ideal steady models, not actual hardware, CFD accuracy or universal Agent planning.",
                               "No LLM scoring, business database, network or external solver execution. Each case uses temporary SQLite."],
                  catalog_sha256=digest(catalog), implementation_sha256={name: hashlib.sha256((project / name).read_bytes()).hexdigest() for name in implementation_files},
                  total=len(results), passed=sum(r["passed"] for r in results), failed=sum(not r["passed"] for r in results),
                  dimensions=summary, results=results)
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# Engineering Agent Benchmark", "", f"Dataset: {DATASET_VERSION} · Oracle: {ORACLE_VERSION}", "",
             "真实 TaskService → Agent/工具 → 物理验证 → 报告；临时 SQLite 与受控知识 fixture。**不是生产 RAG 召回或真实 CFD 评价。**", "",
             f"通过 {report['passed']}/{report['total']}，失败 {report['failed']}。不适用维度单独记录，不计作通过。", "",
             "| Case | 内容 | 服务状态 | 验收 |", "|---|---|---|---|"]
    lines += [f"| {r['case_id']} | {r['title']} | {r['observed_status']} | {'PASS' if r['passed'] else 'FAIL'} |" for r in results]
    lines += ["", "## 分维结果", "", "| 维度 | 通过 | 失败 | 不适用 |", "|---|---:|---:|---:|"]
    lines += [f"| {name} | {s['passed']} | {s['failed']} | {s['not_applicable']} |" for name, s in summary.items()]
    lines += ["", "## 失败原因", ""]
    failures = [f"- {r['case_id']} / {dimension} / {c['check']}: actual={c['actual']!r}; expected={c['expected']!r}" for r in results for dimension, data in r["dimensions"].items() for c in data["checks"] if not c["passed"]]
    lines += failures or ["未发现失败项。"]
    lines += ["", "## 可复现记录", "", f"Catalog SHA-256: `{report['catalog_sha256']}`", "",
              "results.json 含每例输入hash、语义输出hash、planner/tool版本、分项实际/期望值与耗时。receipt文件保留实际初始计划、最终任务和检索查询。UUID/时间戳不要求重复一致；数值与语义输出hash应一致。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return output, report
