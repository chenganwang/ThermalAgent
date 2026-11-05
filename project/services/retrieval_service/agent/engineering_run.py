"""A bounded, pre-execution plan for the existing deterministic calculation path.

This receipt follows the existing selected calculation without replanning or replay.
Optional observers persist execution checkpoints through the engineering service;
the receipt itself does not perform storage or record private LLM reasoning.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Callable, get_args
from uuid import uuid4

from services.physics_service.contracts import PhysicsValidationRequest, Unit
from services.physics_service.validator import validate_physics
from ..tools.executor import _missing_result
from ..tools.specs import TOOL_SPECS
from ..tools.versions import THERMAL_TOOL_VERSION, THERMAL_MODEL_VERSION
from services.engineering_service.result_identity import ResultIdentityError, assert_run_result, bind_result


OUTPUT_UNITS = {
    "heat_rate_W": "W", "heat_flux_W_m2": "W/m2", "R_cond_K_per_W": "K/W",
    "R_required_K_per_W": "K/W", "allowed_delta_T_K": "K", "delta_T_K": "K",
    "temperature_rise_K": "K", "T_j_C": "degC", "T_out_C": "degC",
    "margin_to_limit_C": "K", "mass_flow_kg_s": "kg/s", "volume_flow_m3_s": "m3/s",
    "volume_flow_L_min": "L/min",
}
LIMITATIONS = [
    "仅编排本次选定的确定性计算工具；不代表通用自主规划或真实多 Agent 调度。",
    "执行记录随响应返回，尚无跨进程持久变量账本或自动重放。",
    "物理检查仅覆盖声明的规则和适用域，通过不等于真实工程设计已验收。",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_safe(value), ensure_ascii=False, sort_keys=True,
                                     allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _transition(run: dict, step_id: str, status: str, error: str | None = None) -> None:
    step = next(item for item in run["steps"] if item["step_id"] == step_id)
    at = _now()
    step["status"] = status
    if status == "running":
        step["started_at"] = at
    else:
        step["finished_at"] = at
    if error:
        step["error"] = error
    run["events"].append({"sequence": len(run["events"]) + 1, "step_id": step_id, "status": status, "at": at})


def plan_calculation(tool_name: str, parsed: dict) -> dict:
    """Freeze a tool/input contract before any numeric executor is invoked."""
    spec = TOOL_SPECS[tool_name]
    inputs = deepcopy(parsed.get("inputs") or {})
    assumptions = list(parsed.get("assumptions") or [])
    missing = list(parsed.get("missing_parameters") or [])
    steps = [("structure_inputs", "整理参数与缺项", []),
             ("calculation", "执行已选定的计算工具", ["structure_inputs"]),
             ("validation", "检查数值与物理约束", ["calculation"]),
             ("evidence", "关联知识来源", []),
             ("report", "整理工程报告（按请求）", ["calculation", "validation", "evidence"])]
    run = {"schema_version": "1.0", "run_id": "engineering_" + uuid4().hex,
           "scope": "deterministic_calculation", "status": "planned", "created_at": _now(),
           "tool_name": tool_name, "tool_version": THERMAL_TOOL_VERSION, "model_version": THERMAL_MODEL_VERSION, "identity_version": 2,
           "problem": {"description": spec.description, "required_parameters": list(spec.required_params),
                       "missing_parameters": missing, "assumptions": assumptions},
           "formula": spec.formula, "input_snapshot": _safe(inputs),
           "input_fingerprint": _hash({"tool": spec.to_dict(), "version": THERMAL_TOOL_VERSION, "model_version": THERMAL_MODEL_VERSION, "inputs": inputs}),
           "steps": [{"step_id": key, "title": title, "depends_on": deps, "status": "pending"}
                     for key, title, deps in steps], "events": [],
           "variables": [{"name": name, "value": _safe(value), "unit": spec.units.get(name),
                          "role": "input", "step_id": "structure_inputs",
                          "source": "query_or_declared_assumption" if assumptions else "parsed_query"}
                         for name, value in inputs.items() if value is not None],
           "validation": {"passed": False, "status": "incomplete", "limitations": ["尚未执行数值检查。"]},
           "evidence": [], "report": {"generated": False}, "limitations": list(LIMITATIONS)}
    _transition(run, "structure_inputs", "blocked" if missing else "completed")
    run["calculation_fingerprint"] = run["input_fingerprint"]
    return run


def _validate_result(result: dict) -> dict:
    explicit = result.get("physics_validation")
    if isinstance(explicit, dict):
        return deepcopy(explicit)
    quantities = []
    for name, value in (result.get("result") or {}).items():
        unit = OUTPUT_UNITS.get(name)
        if unit in get_args(Unit) and isinstance(value, (int, float)) and not isinstance(value, bool):
            quantities.append({"name": name, "value": value, "unit": unit,
                               "quantity_type": "absolute_temperature" if name in {"T_j_C", "T_out_C"} else "scalar"})
    if not quantities:
        return {"passed": False, "status": "incomplete", "limitations": [
            "此工具未提供可供共享校验器检查的明确标量输出；请查阅该工具自己的验证证据。"]}
    validated = validate_physics(PhysicsValidationRequest.model_validate({"quantities": quantities})).model_dump()
    validated["limitations"].append("本次通用输出检查仅检查有限性与明确绝对温度；不验证模型、测量误差或独立数值解。")
    return validated


def execute_calculation_plan(run: dict, parsed: dict, executor: Callable[..., dict], *, observer=None) -> dict:
    """Run the fixed tool once, using the exact input snapshot selected in the plan."""
    fingerprint = _hash({"tool": TOOL_SPECS[run["tool_name"]].to_dict(), "version": run["tool_version"],
                         "model_version": THERMAL_MODEL_VERSION, "inputs": parsed.get("inputs") or {}})
    if (fingerprint != run["input_fingerprint"] or fingerprint != run.get("calculation_fingerprint")
            or run.get("tool_version") != THERMAL_TOOL_VERSION
            or run.get("model_version") != THERMAL_MODEL_VERSION):
        _transition(run, "calculation", "blocked", "计划输入已变化，必须重新生成计划。")
        _transition(run, "validation", "blocked")
        run["status"] = "blocked"
        return {"tool_name": run["tool_name"], "status": "error", "inputs": run["input_snapshot"],
                "result": {}, "formula": run["formula"], "error": "工程计划输入指纹不匹配。", "engineering_run": run}
    if run["problem"]["missing_parameters"]:
        result = _missing_result(parsed)
        _transition(run, "calculation", "blocked", "缺少必要参数，未调用计算函数。")
        _transition(run, "validation", "blocked")
        run["status"] = "blocked"
    else:
        _transition(run, "calculation", "running")
        run["status"] = "running"
        if observer is not None:
            observer(run)
        try:
            # Keep numeric originals (including invalid values) for the tool's own
            # guards; the public snapshot uses JSON-safe representations only.
            result = executor(**deepcopy(parsed.get("inputs") or {}))
        except Exception as exc:
            result = {"tool_name": run["tool_name"], "status": "error", "inputs": parsed.get("inputs") or {},
                      "result": {}, "formula": run["formula"], "error": f"计算执行失败（{type(exc).__name__}）。"}
        try:
            assert_run_result(run, result)
        except ResultIdentityError:
            result = {"tool_name": run["tool_name"], "status": "error", "inputs": deepcopy(run["input_snapshot"]),
                      "result": {}, "formula": run["formula"], "error": "执行结果输入或工具身份不一致，已拒绝返回。",
                      "error_code": "ENGINEERING_RESULT_IDENTITY_MISMATCH",
                      "physics_validation": {"status": "failed", "passed": False}}
        result.setdefault("missing_parameters", [])
        result.setdefault("assumptions", [])
        result.setdefault("warnings", [])
        result["parameter_parse"] = parsed
        for key in ("assumptions", "warnings"):
            for value in parsed.get(key) or []:
                if value not in result[key]:
                    result[key].append(value)
        if result.get("status") != "ok":
            run["status"] = "blocked" if result.get("missing_parameters") else "failed"
            _transition(run, "calculation", run["status"], str(result.get("error") or "计算未产生有效结果。"))
            explicit_validation = result.get("physics_validation")
            if isinstance(explicit_validation, dict) and explicit_validation.get("status") == "failed":
                run["validation"] = deepcopy(explicit_validation)
                _transition(run, "validation", "failed")
            else:
                _transition(run, "validation", "blocked")
        else:
            _transition(run, "calculation", "completed")
            _transition(run, "validation", "running")
            if observer is not None:
                observer(run)
            run["validation"] = _validate_result(result)
            result["physics_validation"] = deepcopy(run["validation"])
            status = run["validation"]["status"]
            _transition(run, "validation", "completed" if status == "passed" else status)
            run["status"] = "completed" if status == "passed" else status
            if status == "failed":
                result["status"] = "error"
                result["error"] = "计算结果未通过已声明的物理约束检查。"
        if run["validation"].get("status") == "failed" and result.get("result"):
            result["rejected_result"] = _safe(result["result"])
            result["result"] = {}
        for name, value in (result.get("result") or {}).items():
            if value is not None:
                run["variables"].append({"name": name, "value": _safe(value), "unit": OUTPUT_UNITS.get(name),
                                         "role": "output", "source": run["tool_name"], "step_id": "calculation"})
    result = bind_result(run, result)
    result["engineering_run"] = run
    if observer is not None:
        observer(run, {key: value for key, value in _safe(result).items() if key != "engineering_run"})
    return _safe(result)


def finish_engineering_run(run: dict, metadata: dict, sources: list[dict]) -> dict:
    """Attach actual evidence and the existing report; never invent solver results."""
    run = deepcopy(run)
    _transition(run, "evidence", "running")
    fields = ("doc_id", "chunk_id", "title", "page_start", "page_end")
    run["evidence"] = list(run.get("evidence") or []) + [{key: source[key] for key in fields if key in source} for source in sources]
    if metadata.get("retrieval_error"):
        _transition(run, "evidence", "failed", "知识检索失败；计算输出仍保留，但来源证据不完整。")
        if run["status"] == "completed":
            run["status"] = "incomplete"
    else:
        _transition(run, "evidence", "completed")
    if not sources:
        run["limitations"].append("本次没有知识来源；计算公式与用户输入是现有证据，不伪造文献支持。")
    report = metadata.get("report") or {}
    if report.get("generated") and report.get("content"):
        _transition(run, "report", "running")
        section = ("\n\n## 工程执行记录\n\n"
                   f"- 运行编号：`{run['run_id']}`\n- 工具：`{run['tool_name']}`（{run['tool_version']}）\n"
                   f"- 输入指纹：`{run['input_fingerprint']}`\n"
                   f"- 执行记录状态：{run['status']}；物理检查：{run['validation']['status']}\n"
                   "- 范围：确定性计算、物理检查与报告关联；真实 CFD 是否执行以求解器记录为准，保存状态以 persistence 字段为准。\n")
        report["content"] += section
        report.setdefault("sections", []).append({"id": "engineering_run", "title": "工程执行记录"})
        run["report"] = {"generated": True, "content_sha256": hashlib.sha256(report["content"].encode("utf-8")).hexdigest()}
        _transition(run, "report", "completed")
    elif report.get("error"):
        _transition(run, "report", "failed", "工程报告生成失败。")
        if run["status"] == "completed":
            run["status"] = "incomplete"
    else:
        _transition(run, "report", "skipped")
    run["finished_at"] = _now()
    return run
