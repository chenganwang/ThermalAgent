"""A bounded liquid cooling DAG assembled from existing pure ToolSpecs."""
from copy import deepcopy
import hashlib
import json
import re

from services.data_asset_service import ProjectionLevel, project_retrieval_source
from services.physics_service.contracts import PhysicsValidationRequest
from services.physics_service.validator import validate_physics
from services.retrieval_service.agent.engineering_run import execute_calculation_plan, finish_engineering_run, plan_calculation
from services.retrieval_service.agent.response_builder import build_agent_response
from services.retrieval_service.agent.contracts import AgentRequest
from services.retrieval_service.agent.state import AgentContext
from services.retrieval_service.agent.stages.retrieval_stage import RetrievalStage
from services.retrieval_service.tools.executor import parse_tool_inputs
from services.retrieval_service.tools.specs import TOOL_FUNCTIONS, TOOL_SPECS
from services.retrieval_service.tools.versions import THERMAL_TOOL_VERSION, LIQUID_WORKFLOW_VERSION
from .execution import RunRecorder, local_report_content
from .design_review import design_review_markdown, run_design_review
from .result_identity import fingerprint, assessment_fingerprint


LIQUID_STEPS = [("structure_inputs", "明确液冷目标与参数", []),
                ("retrieval", "检索液冷设计依据", []),
                ("flow", "计算所需冷却液流量", ["structure_inputs"]),
                ("pressure", "根据流量计算管路压降", ["flow"]),
                ("validation", "检查能量守恒与物理范围", ["flow", "pressure"]),
                ("report", "生成工程分析报告", ["retrieval", "flow", "pressure", "validation"])]
AGENT_STEPS = [("structure_inputs", "理解问题与规划检索", []),
               ("calculation", "执行工程计算", ["structure_inputs"]),
               ("validation", "检查计算结果", ["calculation"]),
               ("properties", "查询工程物性", ["structure_inputs"]),
               ("retrieval", "检索知识与来源", ["structure_inputs"]),
               ("report", "整理工程分析与报告", ["calculation", "retrieval"]),
               ("answer", "生成回答", ["retrieval", "report"])]
UNITS = {"heat_load_w": "W", "coolant_delta_t_k": "K", "specific_heat_j_kgk": "J/(kg*K)",
         "density_kg_m3": "kg/m3", "dynamic_viscosity_pa_s": "Pa*s", "hydraulic_diameter_m": "m",
         "length_m": "m", "minor_loss_coefficient": "1", "mass_flow_kg_s": "kg/s", "volume_flow_m3_s": "m3/s",
         "volume_flow_L_min": "L/min", "pressure_drop_pa": "Pa", "pressure_drop_kpa": "kPa",
         "required_head_m": "m", "velocity_m_s": "m/s", "reynolds_number": "1", "friction_factor": "1",
         "major_loss_pa": "Pa", "minor_loss_pa": "Pa", "flow_rate_m3_s": "m3/s", "flow_rate_lpm": "L/min"}
LIMITATIONS = ["采用稳态能量平衡与一维 Darcy–Weisbach 管路估算；不是 CFD 或试验结果。",
               "未计算芯片结温、详细冷板通道换热、泵曲线工作点、NPSH 或分流均匀性。",
               "物性为用户显式输入或已声明的近室温水假设，未自动认定为知识库测量值。"]


def declared_steps(liquid):
    steps = []
    for key, title, deps in LIQUID_STEPS if liquid else AGENT_STEPS:
        step = {"step_id": key, "title": title, "depends_on": list(deps), "status": "pending", "inputs": {}, "outputs": {},
                "dependency_policy": "after_terminal" if key in {"report", "answer"} else "requires_success"}
        tool = {"flow": "liquid_flow_rate_required", "pressure": "liquid_pressure_drop_estimate"}.get(key) if liquid else None
        if tool:
            step.update(tool_name=tool, tool_version=THERMAL_TOOL_VERSION, formula=TOOL_SPECS[tool].formula)
        if key == "pressure":
            step["input_bindings"] = {"flow_rate_lpm": {"step_id": "flow", "output": "volume_flow_L_min", "unit": "L/min"}}
        steps.append(step)
    return steps


def is_liquid_task(request):
    if request.get("reference_solver") is not None:
        return False
    query = request["query"].lower()
    return request.get("liquid_cooling") is not None or bool(
        re.search(r"液冷|水冷|冷板|liquid.cool|cold.plate", query) and
        (re.search(r"设计|方案|design|规划", query) or ("流量" in query and "压降" in query)))


def liquid_inputs(request):
    query = request["query"]
    flow = parse_tool_inputs(query, "liquid_flow_rate_required")
    hydraulic = parse_tool_inputs(query, "liquid_pressure_drop_estimate")
    f, h = flow["inputs"], hydraulic["inputs"]
    diameter = h.get("hydraulic_diameter_mm")
    values = dict(heat_load_w=f.get("Q_W"), coolant_delta_t_k=f.get("delta_T_K"), specific_heat_j_kgk=f.get("cp_J_kgK"),
                  density_kg_m3=f.get("rho_kg_m3"), dynamic_viscosity_pa_s=h.get("dynamic_viscosity_pa_s"),
                  hydraulic_diameter_m=diameter / 1000 if diameter is not None else None, length_m=h.get("length_m"),
                  minor_loss_coefficient=h.get("minor_loss_coefficient_k"))
    origins = {key: "parsed_query" for key, value in values.items() if value is not None}
    for key, value in (request.get("liquid_cooling") or {}).items():
        if value is not None:
            values[key], origins[key] = value, "explicit_structured_input"
    assumptions = []
    if flow.get("fluid_name") == "water":
        for key, value in (("specific_heat_j_kgk", 4180.), ("density_kg_m3", 1000.), ("dynamic_viscosity_pa_s", .001)):
            if values[key] is None:
                values[key], origins[key] = value, "declared_water_assumption"
                assumptions.append(f"明确指定水，采用近室温近似 {key}={value} {UNITS[key]}。")
    if values["minor_loss_coefficient"] is None:
        values["minor_loss_coefficient"], origins["minor_loss_coefficient"] = 0., "declared_omission"
        assumptions.append("未提供局部损失系数，暂取 K=0；所得压降不包含未声明的弯头、接头等局部损失。")
    return values, origins, assumptions


def _quantities(values, *, outputs=False):
    allowed = {"W", "K", "Pa", "kPa", "m", "m/s", "kg/s", "m3/s", "1", "J/(kg*K)"}
    return [{"name": key, "value": value, "unit": UNITS[key], "positive": key not in {"minor_loss_coefficient", "minor_loss_pa"}}
            for key, value in values.items() if isinstance(value, (int, float)) and not isinstance(value, bool) and UNITS.get(key) in allowed]


def execute_tool(ctx, step_id, tool, inputs, *, input_sources=None):
    spec = TOOL_SPECS[tool]
    ctx.transition(step_id, "running", "已固定输入，开始调用本地确定性计算工具。", inputs=inputs,
                   tool_name=tool, tool_version=THERMAL_TOOL_VERSION, formula=spec.formula,
                   input_sources=input_sources or {key: "structure_inputs" for key in inputs})
    parsed = {"tool_name": tool, "inputs": deepcopy(inputs),
              "missing_parameters": [key for key in spec.required_params if inputs.get(key) is None], "assumptions": [], "warnings": []}
    run = plan_calculation(tool, parsed)
    run.update({key: ctx.task[key] for key in ("task_id", "session_id", "request_fingerprint")})
    ctx.task.setdefault("run_ids", []).append(run["run_id"])
    recorder = RunRecorder(ctx.service.run_store, {"origin": "engineering_task", "task_id": ctx.task["task_id"]},
                           ctx.request.get("engineering_project_id") or "local")
    try:
        recorder(run)
        if not recorder.state.get("saved"):
            raise RuntimeError("Run checkpoint failed before execution")
        def checked_executor(**kwargs):
            result = TOOL_FUNCTIONS[tool](**kwargs)
            if result.get("status") == "ok":
                quantities = _quantities(result.get("result") or {}, outputs=True)
                result["physics_validation"] = validate_physics(PhysicsValidationRequest.model_validate({"quantities": quantities})).model_dump()
                result["physics_validation"]["limitations"].append("原计算器输出带舍入；小量的有效位数不足可导致零值或闭合检查失败，不代表物理定律失效。")
            return result
        result = execute_calculation_plan(run, parsed, checked_executor, observer=recorder)
        run = result.pop("engineering_run")
        if not recorder.state.get("saved"):
            raise RuntimeError("Run checkpoint failed")
        success = result.get("status") == "ok" and run["validation"].get("passed")
        ctx.add_variables(step_id, inputs, "input", input_sources or {key: "structure_inputs" for key in inputs}, spec.units)
        if success:
            ctx.add_variables(step_id, result["result"], "output", tool, UNITS)
        ctx.transition(step_id, "completed" if success else "failed",
                       "计算完成，已保存实际结果。" if success else "计算或共享数值检查未通过，请检查输入和有效位数。",
                       outputs=result.get("result") or {}, calculation_result=result, run_id=run["run_id"],
                       error=None if success else {"code": "CALCULATION_FAILED", "message": "计算或共享数值检查未通过，请检查输入和有效位数。"})
        retrieval_failed = any(step["step_id"] == "retrieval" and step["status"] == "failed" for step in ctx.task["steps"])
        metadata = {"report": {"generated": True, "content": local_report_content(run)},
                    "retrieval_error": "知识检索未完成。" if retrieval_failed else None}
        run = finish_engineering_run(run, metadata, ctx.task.get("evidence") or [])
        recorder(run, result, metadata["report"]["content"])
        if not recorder.state.get("saved"):
            raise RuntimeError("Run report checkpoint failed")
        return result if success else None
    finally:
        recorder.close()


def liquid_report(task):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# 液冷工程任务报告", "", task["query"], "", f"任务状态：{task.get('outcome', task['status'])}", "",
             "## 参数与中间结果", "", "| 步骤 | 角色 | 变量 | 数值 | 单位 | 来源 |", "|---|---|---|---|---|---|"]
    for v in task["variables"]:
        lines.append("| " + " | ".join(cell(v.get(k, "")) for k in ("step_id", "role", "name", "value", "unit", "source")) + " |")
    lines += ["", "## 步骤与公式", ""]
    for step in task["steps"]:
        if step["step_id"] != "report":
            formula = step.get("formula")
            # ToolSpec formulas are fixed text; code spans preserve * and _ in Markdown.
            literal_formula = f" `{formula}`" if formula else ""
            lines += [f"- {step['title']}：{step['status']}。{literal_formula}"]
    validation = task.get("validation") or {}
    lines += ["", "## 物理检查", "", f"检查状态：{validation.get('status', '未完成')}；能量相对偏差：{validation.get('energy_relative_error', '未检查')}。"]
    lines += ["", "## 假设与限制", "", *["- " + cell(x) for x in task.get("assumptions", []) + LIMITATIONS]]
    if task.get("missing_parameters"):
        lines += ["", "缺少参数：" + "、".join(task["missing_parameters"]) + "。未执行缺参计算。"]
    lines += ["", "## 知识来源", ""]
    for source in task.get("evidence") or []:
        lines.append(f"- {cell(source.get('title', ''))}；doc={source.get('doc_id')}，chunk={source.get('chunk_id')}，页码={source.get('page_start')}–{source.get('page_end')}。")
    if not task.get("evidence"):
        lines.append("知识库未提供可引用依据；本报告仅记录输入和确定性公式证据。")
    return "\n".join(lines) + "\n" + design_review_markdown(task.get("design_review"))


def retrieve_task_evidence(ctx, agent):
    """Use the same RAG normalization and absence/error semantics in bounded plans."""
    ctx.transition("retrieval", "running", "通过原 Agent 检索接口读取知识来源。")
    query = ctx.request["query"]
    if ctx.task.get("continuation"):
        query = ctx.task["continuation"]["root_query"] + "\n本轮明确修改：" + query
    analysis = agent.analyze(query, session_id=ctx.request["session_id"])
    context = AgentContext(request=AgentRequest(query=analysis.resolved_query, session_id=ctx.request["session_id"], top_k=ctx.request["top_k"]),
                           task={**analysis.task.to_dict(), "needs_retrieval": True}, rewrite=analysis.rewrite.to_dict(),
                           intermediate={"rewrite_result": analysis.rewrite})
    RetrievalStage(cfg=agent.cfg, retriever_func=agent.retriever_func).run(context)
    retrieval = context.intermediate["retrieval_result"]
    sources = [project_retrieval_source(s, ProjectionLevel.LLM_SAFE) for s in context.sources]
    ctx.task["evidence"] = sources
    status = "failed" if retrieval.get("error") else "completed" if sources else "incomplete"
    ctx.transition("retrieval", status, f"实际返回 {len(sources)} 条可引用来源。" if sources else "知识库未提供可引用依据。",
                   outputs={"retrieval_count": len(sources)}, error={"code": "RETRIEVAL_UNAVAILABLE", "message": "知识检索未完成。"} if retrieval.get("error") else None)
    return analysis, sources, retrieval, status


def run_liquid_workflow(ctx, agent):
    ctx.transition("structure_inputs", "running", "解析原问题的显式单位与参数。")
    values, origins, assumptions = liquid_inputs(ctx.request)
    if ctx.task.get("continuation"):
        assumptions = list(dict.fromkeys([*ctx.task["continuation"].get("inherited_assumptions", []), *assumptions]))
    missing = [key for key, value in values.items() if value is None]
    calculation_fingerprint = fingerprint({"inputs": values, "units": UNITS, "model_version": LIQUID_WORKFLOW_VERSION,
        "tools": {name: TOOL_SPECS[name].to_dict() for name in ("liquid_flow_rate_required", "liquid_pressure_drop_estimate")},
        "tool_version": THERMAL_TOOL_VERSION})
    ctx.task.update(assumptions=assumptions, missing_parameters=missing, calculation_fingerprint=calculation_fingerprint,
                    input_fingerprint=assessment_fingerprint(calculation_fingerprint, ctx.request.get("design_criteria")))
    for key, value in values.items():
        if value is not None:
            ctx.add_variables("structure_inputs", {key: value}, "input", origins[key], UNITS)
    invalid = [key for key, value in values.items() if value is not None and
               (value < 0 if key == "minor_loss_coefficient" else value <= 0)]
    ctx.transition("structure_inputs", "blocked" if missing or invalid else "completed",
                   "缺少必要参数，后续数值步骤被阻断。" if missing or invalid else "参数已保存；计划依赖已固定。", inputs=values)
    analysis, sources, retrieval, retrieval_status = retrieve_task_evidence(ctx, agent)
    success = False
    if missing or invalid:
        ctx.task["outcome"] = "blocked"
        for key in ("flow", "pressure", "validation"):
            ctx.transition(key, "blocked", "必要输入不完整或不合法，未执行。")
    else:
        f = execute_tool(ctx, "flow", "liquid_flow_rate_required", {"Q_W": values["heat_load_w"], "delta_T_K": values["coolant_delta_t_k"],
                         "cp_J_kgK": values["specific_heat_j_kgk"], "rho_kg_m3": values["density_kg_m3"]})
        p = None
        if f:
            p = execute_tool(ctx, "pressure", "liquid_pressure_drop_estimate", {
                "flow_rate_lpm": f["result"]["volume_flow_L_min"], "hydraulic_diameter_mm": values["hydraulic_diameter_m"] * 1000,
                "length_m": values["length_m"], "density_kg_m3": values["density_kg_m3"],
                "dynamic_viscosity_pa_s": values["dynamic_viscosity_pa_s"], "minor_loss_coefficient_k": values["minor_loss_coefficient"]},
                input_sources={"flow_rate_lpm": "flow.volume_flow_L_min", "hydraulic_diameter_mm": "structure_inputs.hydraulic_diameter_m × 1000 (m→mm)",
                    "length_m": "structure_inputs.length_m", "density_kg_m3": "structure_inputs.density_kg_m3",
                    "dynamic_viscosity_pa_s": "structure_inputs.dynamic_viscosity_pa_s", "minor_loss_coefficient_k": "structure_inputs.minor_loss_coefficient"})
        else:
            ctx.transition("pressure", "blocked", "上游流量没有通过验证，不执行压降。")
        if f and p:
            ctx.transition("validation", "running", "检查实际流量、压降、扬程与稳态能量偏差。")
            validation = validate_physics(PhysicsValidationRequest.model_validate({
                "quantities": _quantities({**f["result"], **p["result"]}, outputs=True),
                "energy_balance": {"heat_input_w": values["heat_load_w"], "heat_output_w": p["result"]["flow_rate_m3_s"] * values["density_kg_m3"] * values["specific_heat_j_kgk"] * values["coolant_delta_t_k"], "relative_tolerance": 1e-5}})).model_dump()
            validation["limitations"].append("链间传递全精度 L/min，并由压降工具换算为 m3/s；能量闭合采用实际体积流量，展示舍入不参与下游计算。")
            if not validation["passed"]:
                validation["limitations"].append("该计算器输出带数值舍入；小流量或极端参数可能缺少满足闭合容差的有效位数。未通过检查不表示物理守恒定律失效，不能把此数值结果作为已验证设计。")
            ctx.task["validation"] = validation
            success = validation["passed"]
            ctx.transition("validation", "completed" if success else "failed", "物理约束检查通过。" if success else "数值未满足声明的物理闭合容差；请检查输入与计算精度。", outputs=validation,
                error=None if success else {"code": "NUMERICAL_CONSISTENCY_FAILED", "message": "计算结果未满足闭合容差，可能受有效位数或模型输入影响。"})
        else:
            ctx.transition("validation", "blocked", "上游计算未完成，未验证整条链。")
        ctx.task["outcome"] = ("completed" if retrieval_status == "completed" else "incomplete") if success else "failed"
    measured = {name: value for step in ctx.task["steps"] if step["step_id"] in {"flow", "pressure"} and step["status"] == "completed" for name, value in step.get("outputs", {}).items()}
    run_design_review(ctx, measured)
    ctx.transition("report", "running", "依据已保存的输入、结果、物理检查和来源生成报告。")
    content = liquid_report(ctx.task)
    report = {"generated": True, "title": "液冷工程任务报告", "content": content,
              "content_sha256": hashlib.sha256(content.encode()).hexdigest(), "sections": [{"id": "task_steps", "title": "任务执行与依据"}]}
    ctx.task["report"] = {key: value for key, value in report.items() if key != "content"}
    response = build_agent_response(answer_text=content, query=ctx.task["query"], task_type="liquid_cooling_design",
        task={**analysis.task.to_dict(), "task_type": "liquid_cooling_design"}, rewrite=analysis.rewrite.to_dict(), sources=sources,
        session_id=ctx.request["session_id"], metadata={"report": report, "retrieval_error": "知识检索未完成。" if retrieval.get("error") else None,
        "used_calculation": any(step.get("outputs") for step in ctx.task["steps"] if step["step_id"] in {"flow", "pressure"}),
        "calculation": {"used_calculation": bool(success), "tool_name": "liquid_cooling_chain", "tool_status": ctx.task["outcome"],
                        "tool_result": {s["step_id"]: s["outputs"] for s in ctx.task["steps"] if s["step_id"] in {"flow", "pressure"}}},
        "engineering_task": {"task_id": ctx.task["task_id"], "scope": "bounded_liquid_cooling", "status": ctx.task["outcome"]},
        "design_review": ctx.task.get("design_review"),
        "physics_validation": ctx.task.get("validation") or {"status": "incomplete", "passed": False}})
    ctx.transition("report", "completed", "工程报告已生成并记录内容哈希。", outputs={"content_sha256": report["content_sha256"]})
    return response
