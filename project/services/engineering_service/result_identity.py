"""Versioned engineering input identities and fail-closed result ownership checks.

Calculation identity is independent of a design assessment. Neither identity is a
Run ID: identical work may share a calculation key, never a mutable Run receipt.
"""
from copy import deepcopy
import hashlib
import json

REFERENCE_TOOL = "reference_layered_wall_solve"
REFERENCE_VERSION = "layered-wall-reference-v1"
REFERENCE_MODEL_VERSION = "steady-1d-constant-k-v1"
REFERENCE_UNITS = {"area_m2": "m2", "left_temperature_k": "K", "right_temperature_k": "K",
                   "layers.thickness_m": "m", "layers.conductivity_w_mk": "W/(m*K)"}
REVIEW_VERSION = "explicit-design-limits-v1"
DESIGN_UNITS = {"max_pressure_drop_pa": "Pa", "max_volume_flow_l_min": "L/min",
                "max_thermal_resistance_k_w": "K/W", "max_heat_rate_abs_w": "W"}


class ResultIdentityError(ValueError):
    """The result must not be served, persisted or displayed as this execution."""


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def reference_calculation_fingerprint(inputs, *, tool_version=REFERENCE_VERSION,
                                      model_version=REFERENCE_MODEL_VERSION, units=None):
    return fingerprint({"identity_version": 2, "tool_name": REFERENCE_TOOL, "tool_version": tool_version,
                        "model_version": model_version, "units": REFERENCE_UNITS if units is None else units,
                        "inputs": inputs})


def assessment_fingerprint(calculation_fingerprint, criteria):
    return fingerprint({"identity_version": 2, "calculation_fingerprint": calculation_fingerprint,
                        "design_criteria": {k: v for k, v in (criteria or {}).items() if v is not None},
                        "design_units": DESIGN_UNITS, "reviewer_version": REVIEW_VERSION})


def assert_reference_result(run, solved):
    """Check the solver's own receipt, independently of the caller's cache key."""
    expected = reference_calculation_fingerprint(run["input_snapshot"])
    if (solved.get("input_fingerprint") != expected
            or canonical(solved.get("inputs")) != canonical(run["input_snapshot"])
            or solved.get("solver_version") != run["tool_version"]
            or solved.get("model") != run["input_snapshot"]["model"]
            or solved.get("units") != REFERENCE_UNITS):
        raise ResultIdentityError("Solver result inputs, units or version do not match this Run")


def assert_run_result(run, result, *, require_identity=False):
    if not result or result.get("status") != "ok":
        return
    if result.get("tool_name") != run["tool_name"]:
        raise ResultIdentityError("Calculation result belongs to another tool")
    # Legacy hydraulic tools echo derived SI values and declared defaults too.
    # Compare every supplied field, accounting only for that tool's documented
    # round-trip of L/min through m3/s; no broad numeric tolerance is used.
    strip_none = lambda value: {k: v for k, v in (value or {}).items() if v is not None}
    expected = strip_none(run["input_snapshot"])
    actual = strip_none(result.get("inputs"))
    if run["tool_name"] == "liquid_pressure_drop_estimate" and "flow_rate_lpm" in expected:
        expected["flow_rate_lpm"] = float(expected["flow_rate_lpm"]) / 60000.0 * 60000.0
    if any(key not in actual or canonical(actual[key]) != canonical(value) for key, value in expected.items()):
        raise ResultIdentityError("Calculation result inputs do not match this Run")
    for key in ("run_id", "input_fingerprint", "calculation_fingerprint"):
        if require_identity and run.get("identity_version") == 2 and not result.get(key):
            raise ResultIdentityError("Saved calculation result lacks its execution identity")
        if result.get(key) is not None and result[key] != run.get(key):
            raise ResultIdentityError("Calculation result identity does not match this Run")
    if run.get("identity_version") == 2 and result.get("reference_solver"):
        assert_reference_result(run, result["reference_solver"])
        values = {v["name"]: v["value"] for v in result["reference_solver"].get("metrics", [])}
        if canonical(values) != canonical(result.get("result")):
            raise ResultIdentityError("Projected calculation values do not match the solver receipt")
    outputs = {v["name"]: v["value"] for v in run.get("variables", []) if v.get("role") == "output"}
    if outputs and any(key not in result.get("result", {}) or canonical(result["result"][key]) != canonical(value)
                       for key, value in outputs.items()):
        raise ResultIdentityError("Saved calculation values do not match the Run variables")


def bind_result(run, result):
    assert_run_result(run, result)
    return {**result, **{k: run[k] for k in ("run_id", "input_fingerprint", "calculation_fingerprint") if k in run}}


def task_identity(task):
    keys = ("task_id", "session_id", "request_fingerprint", "input_fingerprint", "calculation_fingerprint", "run_id", "run_ids")
    return {key: deepcopy(task[key]) for key in keys if key in task}


def assert_task_result(task):
    result = task.get("result")
    if not result:
        return
    metadata = result.get("metadata") or {}
    owner = metadata.get("engineering_task") or {}
    if owner.get("task_id") != task["task_id"]:
        raise ResultIdentityError("Answer belongs to another engineering task")
    for key, value in task_identity(task).items():
        if task.get("identity_version") == 2 and owner.get(key) != value:
            raise ResultIdentityError("Answer identity does not match the task request")
    if result.get("session_id") != task["request"]["session_id"] or result.get("query") != task["query"]:
        raise ResultIdentityError("Answer belongs to another conversation or question")
    run = metadata.get("engineering_run")
    if run:
        for key in ("run_id", "input_fingerprint", "task_id", "session_id", "request_fingerprint"):
            if task.get(key) is not None and run.get(key) != task[key]:
                raise ResultIdentityError("Answer Run does not belong to this task")
        calculation = metadata.get("calculation") or {}
        if task.get("identity_version") == 2 and calculation.get("used_calculation"):
            assert_run_result(run, {"status": "ok", "tool_name": calculation.get("tool_name"),
                "inputs": calculation.get("tool_inputs"), "result": calculation.get("tool_result"),
                "reference_solver": metadata.get("reference_solver")})
    if task.get("scope") == "bounded_reference_conduction":
        expected = reference_calculation_fingerprint(task["request"]["reference_solver"])
        if task.get("identity_version") == 2:
            if task.get("calculation_fingerprint") != expected or task.get("input_fingerprint") != assessment_fingerprint(expected, task["request"].get("design_criteria")):
                raise ResultIdentityError("Current task inputs differ from the result fingerprint")
        if run and canonical(run["input_snapshot"]) != canonical(task["request"]["reference_solver"]):
            raise ResultIdentityError("Current physical inputs differ from the execution snapshot")
        review = metadata.get("design_review") or {}
        if task.get("identity_version") == 2:
            if canonical(task.get("design_review") or {}) != canonical(review):
                raise ResultIdentityError("Task summary design review differs from its answer")
            if not task["request"].get("design_criteria") and review:
                raise ResultIdentityError("An undeclared design limit has a stale review")
            values = (metadata.get("calculation") or {}).get("tool_result") or {}
            if any(row["name"] not in values or canonical(row["value"]) != canonical(values[row["name"]])
                   for row in task.get("variables", []) if row.get("role") == "output"):
                raise ResultIdentityError("Task summary values differ from its execution")
        if task.get("identity_version") == 2 and task["request"].get("design_criteria"):
            actual_limits = {row["criterion"]: row["maximum"] for row in review.get("checks", [])}
            expected_limits = {k: v for k, v in task["request"]["design_criteria"].items() if v is not None}
            if canonical(actual_limits) != canonical(expected_limits):
                raise ResultIdentityError("Design review belongs to different limits")
            from .design_review import evaluate_design
            expected_review = evaluate_design(expected_limits, (metadata.get("calculation") or {}).get("tool_result") or {})
            for key in ("reviewer_version", "status", "passed"):
                if canonical(review.get(key)) != canonical(expected_review[key]):
                    raise ResultIdentityError("Design review does not match current limits and numeric results")
            actual_checks = {row["criterion"]: row for row in review.get("checks", [])}
            expected_checks = {row["criterion"]: row for row in expected_review["checks"]}
            if len(actual_checks) != len(review.get("checks", [])) or canonical(actual_checks) != canonical(expected_checks):
                raise ResultIdentityError("Design review checks do not match current limits and numeric results")


def assert_agent_result(result):
    """Validate the final synchronous answer, including projections made by stages."""
    metadata = result.get("metadata") or {}
    run = metadata.get("engineering_run")
    if not run:
        return
    if run.get("session_id") is not None and run["session_id"] != result.get("session_id"):
        raise ResultIdentityError("Synchronous answer belongs to another conversation")
    calculation = metadata.get("calculation") or {}
    outputs = any(value.get("role") == "output" for value in run.get("variables", []))
    specialized = run.get("tool_name") in {"thermal_resistance_network_solve", "liquid_network_flow_distribution",
                                           "liquid_pressure_drop_estimate", "pump_selection_preparer"}
    if specialized:
        # These established tools intentionally use dedicated metadata cards,
        # not the scalar calculation slot. Verify the actual tool receipt first
        # and then every field produced by its existing deterministic projector.
        from services.retrieval_service.agent.metadata_builder import (flow_distribution_metadata,
            hydraulic_network_metadata, hydraulics_metadata, pump_selection_metadata, sensitivity_metadata,
            thermal_network_metadata, thermal_path_metadata)
        raw = metadata.get("calculation_result")
        if not isinstance(raw, dict) or raw.get("tool_name") != run["tool_name"]:
            raise ResultIdentityError("Specialized engineering answer lacks its tool receipt")
        assert_run_result(run, raw)
        tool = run["tool_name"]
        if tool == "thermal_resistance_network_solve":
            projections = {"thermal_network": thermal_network_metadata(raw), "thermal_path": thermal_path_metadata(raw),
                           "sensitivity": sensitivity_metadata(raw.get("sensitivity"))}
        elif tool == "liquid_network_flow_distribution":
            projections = {"flow_distribution": flow_distribution_metadata(raw),
                           "hydraulic_network": hydraulic_network_metadata((raw.get("inputs") or {}).get("network"), raw)}
        elif tool == "liquid_pressure_drop_estimate":
            projections = {"hydraulics": hydraulics_metadata(raw)}
        else:
            projections = {"pump_selection": pump_selection_metadata(raw.get("pump_selection") or raw.get("result"))}
        for section, expected_projection in projections.items():
            actual_projection = metadata.get(section) or {}
            if any(canonical(actual_projection.get(key)) != canonical(value) for key, value in expected_projection.items()):
                raise ResultIdentityError("Specialized engineering projection differs from its current tool result")
    elif calculation.get("used_calculation") or outputs:
        assert_run_result(run, {"status": "ok", "tool_name": calculation.get("tool_name"),
            "inputs": calculation.get("tool_inputs"), "result": calculation.get("tool_result") or {},
            "reference_solver": metadata.get("reference_solver")})
    if run.get("tool_name") != REFERENCE_TOOL or run.get("identity_version") != 2:
        return
    expected = reference_calculation_fingerprint(run["input_snapshot"])
    criteria = run.get("design_criteria") or {}
    if run.get("calculation_fingerprint") != expected or run.get("input_fingerprint") != assessment_fingerprint(expected, criteria):
        raise ResultIdentityError("Synchronous answer input or design identity changed")
    if outputs and not metadata.get("reference_solver"):
        raise ResultIdentityError("Synchronous reference answer lacks the solver receipt")
    review = metadata.get("design_review") or {}
    if criteria or review:
        from .design_review import evaluate_design
        expected_review = evaluate_design(criteria, calculation.get("tool_result") or {})
        for key in ("reviewer_version", "status", "passed"):
            if review.get(key) != expected_review[key]:
                raise ResultIdentityError("Synchronous design review does not match current inputs")
        actual = review.get("checks") or []
        by_criterion = {row["criterion"]: row for row in actual}
        if len(by_criterion) != len(actual) or canonical(by_criterion) != canonical({row["criterion"]: row for row in expected_review["checks"]}):
            raise ResultIdentityError("Synchronous design review checks do not match current values")
