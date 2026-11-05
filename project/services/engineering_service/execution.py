"""Persistence observer and bounded recovery for existing deterministic tools."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .store import EngineeringStore, RunConflict, now
from .result_identity import (ResultIdentityError, assessment_fingerprint, assert_reference_result,
                              assert_run_result, bind_result, reference_calculation_fingerprint)


def configured_store(project_root):
    if os.getenv("ENGINEERING_PERSISTENCE_ENABLED", "true").lower() in {"false", "0", "off"}:
        return None
    path = os.getenv("ENGINEERING_STORE_PATH", "").strip()
    location = Path(path) if path else Path("runtime") / "engineering" / "records.sqlite3"
    return EngineeringStore(location if location.is_absolute() else Path(project_root) / location)


class RunRecorder:
    """One recorder per request. Storage faults are reported without hiding results."""
    def __init__(self, store, request, project_id="local", *, parent_run_id=None):
        self.store, self.request, self.project_id = store, request, project_id
        self.parent_run_id = parent_run_id
        self.lock = None
        self.state = {"saved": False, "enabled": store is not None}
        self.failed = False

    def __call__(self, run, result=None, report=None):
        # Identity faults are not ordinary storage degradation: never save or
        # advertise a result produced for another set of inputs.
        assert_run_result(run, result)
        if self.store is None or self.failed:
            return
        try:
            if self.lock is None:
                self.lock = self.store.lock(run["run_id"])
            run["model_version"] = run.get("model_version", "deterministic-formula-v2.1")
            run["project_id"] = self.project_id
            run["limitations"] = [s for s in run.get("limitations", []) if "尚无跨进程" not in s]
            self.state = {"enabled": True, **self.store.save(
                run, self.request, project_id=self.project_id, result=result, report=report,
                parent_run_id=self.parent_run_id)}
        except Exception as exc:
            self.failed = True
            self.state = {"enabled": True, "saved": False, "error_code": "ENGINEERING_PERSISTENCE_FAILED",
                          "error_type": type(exc).__name__,
                          "message": "本次执行记录未完整保存；计算结果仍可查看，请检查本地存储后重试。"}
            self.close()

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def __del__(self):
        # Unexpected request exceptions must not leave an in-process lock behind.
        self.close()


def reference_plan(inputs, design_criteria=None):
    from services.simulation_service.reference import LayeredWallRequest
    request = LayeredWallRequest.model_validate(inputs).model_dump()
    calculation_fingerprint = reference_calculation_fingerprint(request)
    fingerprint = assessment_fingerprint(calculation_fingerprint, design_criteria)
    return {"schema_version": "1.1", "run_id": "engineering_" + uuid4().hex,
            "scope": "reference_calculation", "status": "planned", "created_at": now(),
            "tool_name": "reference_layered_wall_solve", "tool_version": "layered-wall-reference-v1",
            "model_version": "steady-1d-constant-k-v1", "input_snapshot": request,
            "identity_version": 2, "input_fingerprint": fingerprint,
            "calculation_fingerprint": calculation_fingerprint, "design_criteria": deepcopy(design_criteria or {}),
            "problem": {"description": "稳态一维多层壁参考计算", "missing_parameters": [], "assumptions": []},
            "formula": "R_i=L_i/(k_i*A); Q=(T_left-T_right)/sum(R_i); sum_j((T_i-T_j)/R_ij)=0",
            "steps": [{"step_id": key, "title": title, "depends_on": deps, "status": "pending"}
                      for key, title, deps in [("structure_inputs", "验证显式 SI 输入", []),
                      ("calculation", "执行参考求解器", ["structure_inputs"]),
                      ("validation", "解析对照与物理守恒", ["calculation"]),
                      ("evidence", "记录公式与来源", []), ("report", "保存参考工程报告", ["validation"])]],
            "variables": [{"name": k, "value": v, "role": "input", "source": "explicit_structured_input",
                           "step_id": "structure_inputs", "unit": {"area_m2": "m2", "left_temperature_k": "K",
                           "right_temperature_k": "K", "cells_per_layer": "1", "layers": "thickness_m:m;conductivity_w_mk:W/(m*K)"}.get(k)}
                          for k, v in request.items()],
            "events": [], "evidence": [], "report": {"generated": False},
            "validation": {"status": "incomplete", "passed": False},
            "limitations": ["固定的一维稳态模型；不执行 CFD，不自动推断边界温度。"]}


def execute_reference(run, observer=None):
    from services.simulation_service.reference import solve_reference
    from services.retrieval_service.agent.engineering_run import _transition
    if observer:
        observer(run)
    current = reference_plan(run["input_snapshot"], run.get("design_criteria"))
    if any(current[key] != run.get(key) for key in ("input_fingerprint", "calculation_fingerprint", "tool_version", "model_version")):
        _transition(run, "calculation", "blocked", "参考求解计划输入或版本发生变化。")
        _transition(run, "validation", "blocked")
        run["status"] = "blocked"
        return {"tool_name": run["tool_name"], "status": "error", "result": {},
                "error": "参考计划指纹或版本不一致，未执行。", "engineering_run": run}
    _transition(run, "structure_inputs", "completed")
    _transition(run, "calculation", "running")
    run["status"] = "running"
    if observer:
        observer(run)
    solved = solve_reference(run["input_snapshot"]).model_dump(mode="json")
    try:
        assert_reference_result(run, solved)
    except ResultIdentityError:
        _transition(run, "calculation", "failed", "求解结果输入指纹与本次请求不一致，已拒绝旧结果。")
        _transition(run, "validation", "blocked")
        run["status"] = "failed"
        if observer:
            observer(run)
        raise
    run["validation"] = solved.get("validation") or {"status": "incomplete", "passed": False}
    run["verification"] = solved.get("verification") or {}
    run["limitations"] = list(dict.fromkeys(run["limitations"] + solved["limitations"]))
    success = solved["status"] == "completed" and run["validation"]["status"] == "passed"
    run["status"] = "completed" if success else "failed"
    _transition(run, "calculation", "completed" if solved["status"] == "completed" else "failed")
    _transition(run, "validation", "completed" if success else "failed")
    values = {item["name"]: item["value"] for item in solved["metrics"]} if success else {}
    for metric in solved["metrics"] if success else []:
        run["variables"].append({**metric, "role": "output", "source": run["tool_name"], "step_id": "calculation"})
    run["evidence"] = [{"type": "formula", "formula": f, "source": "steady conduction conservation"}
                       for f in solved["formulas"].values()]
    result = {"tool_name": run["tool_name"], "status": "ok" if success else "error",
              "inputs": run["input_snapshot"], "formula": run["formula"], "result": values,
              "physics_validation": run["validation"], "reference_solver": solved,
              "error": None if success else "参考计算未通过数值或物理验证。",
              "warnings": solved["limitations"], "missing_parameters": [], "assumptions": []}
    result = bind_result(run, result)
    if observer:
        observer(run, result)
    return {**result, "engineering_run": run}


def local_report_content(run):
    def cell(value):
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        return text.replace("|", "\\|").replace("\n", " ")

    lines = ["# 工程执行报告", "", f"工具：{run['tool_name']}（{run['tool_version']}）", "",
             f"物理模型版本：{run.get('model_version', 'deterministic-formula-v2.1')}", "",
             f"公式：`{run['formula']}`", "", "## 输入与输出", "",
             "| 角色 | 参数 | 数值 | 单位 |", "|---|---|---|---|"]
    for variable in run["variables"]:
        if variable["name"] not in {"schema_version", "model"}:
            lines.append("| " + " | ".join(cell(value) for value in (
                "输入" if variable["role"] == "input" else "输出", variable["name"],
                variable["value"], variable.get("unit") or "未声明")) + " |")
    validation = run["validation"]
    lines += ["", "## 验证结果", "", f"物理约束：{validation.get('status', 'incomplete')}；"
              f"能量相对偏差：{validation.get('energy_relative_error', '未检查')}。"]
    verification = run.get("verification") or {}
    if verification:
        lines += ["", "| 独立数值检查 | 结果 |", "|---|---|"]
        for name, label in (("analytic_heat_rate_w", "解析热流 (W)"), ("heat_absolute_error_w", "热流绝对误差 (W)"),
                            ("heat_relative_error", "热流相对误差"), ("max_internal_energy_imbalance_w", "最大内部能量不平衡 (W)"),
                            ("cell_count", "离散单元数"), ("absolute_tolerance_w", "绝对容差 (W)"), ("relative_tolerance", "相对容差")):
            lines.append(f"| {label} | {cell(verification.get(name, '未检查'))} |")
        lines += ["", f"解析/节点解交叉验证：{'通过' if verification.get('passed') else '未通过'}。"]
    lines += ["", "## 适用范围", "", *["- " + cell(item) for item in run.get("limitations", [])], "",
              "报告由确定性模板生成；完整输入、来源和计算产物随执行记录保存。", ""]
    return "\n".join(lines)


def finish_local_report(run, result):
    from services.retrieval_service.agent.engineering_run import finish_engineering_run
    content = local_report_content(run)
    content += "\n本接口使用保存或显式提交的输入，未重新检索知识来源。\n"
    metadata = {"report": {"generated": True, "content": content}}
    final = finish_engineering_run(run, metadata, [])
    return final, metadata["report"]["content"]


def resume_run(store, run_id, expected_revision):
    """A new, linked attempt from frozen inputs. Never replay an external solver."""
    from services.retrieval_service.agent.engineering_run import execute_calculation_plan, plan_calculation
    from services.retrieval_service.tools.specs import TOOL_FUNCTIONS
    with store.lock(run_id):
        parent = store.get(run_id)
        receipt = parent["receipt"]
        if parent["status"] == "completed" or parent["resumed_by"] or parent["revision"] != expected_revision:
            raise RunConflict("Run completed, already recovered, or changed; refresh history")
        tool = receipt["tool_name"]
        if tool == "reference_layered_wall_solve":
            plan = reference_plan(receipt["input_snapshot"], receipt.get("design_criteria"))
        elif tool in TOOL_FUNCTIONS:
            # Pure functions only: this registry contains no process/CFD executors.
            parsed = {"tool_name": tool, "inputs": deepcopy(receipt["input_snapshot"]),
                      "missing_parameters": receipt["problem"].get("missing_parameters", []),
                      "assumptions": receipt["problem"].get("assumptions", []), "warnings": []}
            plan = plan_calculation(tool, parsed)
        else:
            raise RunConflict("This tool cannot be recovered automatically")
        plan.setdefault("model_version", "deterministic-formula-v2.1")
        if any(plan.get(key) != receipt.get(key, "deterministic-formula-v2.1" if key == "model_version" else None)
               for key in ("tool_version", "model_version", "input_fingerprint")):
            raise RunConflict("Tool contract changed; create a new reviewed design instead")
        recorder = RunRecorder(store, parent["request"], parent["project_id"], parent_run_id=run_id)
        recorder.lock = store.lock(plan["run_id"])
        try:
            store.save(plan, parent["request"], project_id=parent["project_id"], parent_run_id=run_id,
                       recovery_revision=expected_revision)
            result = execute_reference(plan, recorder) if tool == "reference_layered_wall_solve" else execute_calculation_plan(
                plan, parsed, TOOL_FUNCTIONS[tool], observer=recorder)
            run = result.pop("engineering_run")
            final, report = finish_local_report(run, result)
            recorder(final, result, report)
            if not recorder.state.get("saved"):
                raise RunConflict("Recovery output could not be saved; inspect the child run before retrying")
        finally:
            recorder.close()
    return store.get(plan["run_id"])
