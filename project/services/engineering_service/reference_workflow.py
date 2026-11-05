"""Explicit planning and evidence around the existing deterministic reference solver."""
import hashlib

from services.retrieval_service.agent.engineering_run import finish_engineering_run
from services.retrieval_service.agent.response_builder import build_agent_response
from .design_review import design_review_markdown, run_design_review
from .execution import RunRecorder, execute_reference, local_report_content, reference_plan
from .task_workflow import retrieve_task_evidence
from .result_identity import task_identity


def reference_steps():
    declared = [("structure_inputs", "固定多层导热模型与 SI 参数", []),
                ("retrieval", "检索导热与热阻设计依据", ["structure_inputs"]),
                ("calculation", "计算多层热阻和温度分布", ["structure_inputs", "retrieval"]),
                ("validation", "解析对照与物理守恒检查", ["calculation"]),
                ("report", "生成可追溯导热方案报告", ["retrieval", "calculation", "validation"])]
    steps = [{"step_id": key, "title": title, "depends_on": deps, "status": "pending", "inputs": {}, "outputs": {},
              "dependency_policy": "after_terminal" if key in {"report", "calculation"} else "requires_success"} for key, title, deps in declared]
    steps[2].update(tool_name="reference_layered_wall_solve", tool_version="layered-wall-reference-v1",
                    formula="R_i=L_i/(k_i*A); Q=(T_left-T_right)/sum(R_i)",
                    input_bindings={key: {"step_id": "structure_inputs", "output": key} for key in
                                    ("model", "area_m2", "left_temperature_k", "right_temperature_k", "layers", "cells_per_layer")})
    # Retrieval can legitimately be absent. The explicit model remains calculable,
    # while the final task is incomplete until its knowledge evidence is supplied.
    return steps


def run_reference_workflow(ctx, agent):
    ctx.transition("structure_inputs", "running", "验证并保存显式几何、导热系数和绝对边界温度。")
    run = reference_plan(ctx.request["reference_solver"], ctx.request.get("design_criteria"))
    ctx.task["input_fingerprint"] = run["input_fingerprint"]
    ctx.task["calculation_fingerprint"] = run["calculation_fingerprint"]
    ctx.task["run_id"] = run["run_id"]
    run.update(task_identity(ctx.task))
    ctx.task["model_version"] = run["model_version"]
    ctx.transition("structure_inputs", "completed", "已冻结参考模型及输入；不推断缺失温度或物性。",
                   inputs=run["input_snapshot"], outputs=run["input_snapshot"])
    analysis, sources, retrieval, retrieval_status = retrieve_task_evidence(ctx, agent)
    recorder = RunRecorder(ctx.service.run_store, {"origin": "engineering_task", "task_id": ctx.task["task_id"]},
                           ctx.request.get("engineering_project_id") or "local")

    def observe(record, result=None, report=None):
        recorder(record, result, report)
        if not recorder.state.get("saved"):
            raise RuntimeError("Reference run checkpoint failed")
        ctx.calculation_observer(record, result, report)

    try:
        calculated = execute_reference(run, observe)
        run = calculated.pop("engineering_run")
        ctx.task["verification"] = run.get("verification") or {}
        good = calculated.get("status") == "ok" and run["validation"].get("passed") is True and run["verification"].get("passed") is True
        ctx.task["outcome"] = ("completed" if retrieval_status == "completed" else "incomplete") if good else "failed"
        run_design_review(ctx, calculated.get("result") or {} if good else {})
        run["design_review"] = ctx.task.get("design_review")
        ctx.transition("report", "running", "依据原始输入、实际参考解、解析误差和知识来源汇编报告。")
        content = local_report_content(run)
        content += f"\n\n## 工程任务\n\n{ctx.task['query']}\n\n任务结论：{ctx.task['outcome']}。\n"
        content += design_review_markdown(ctx.task.get("design_review"))
        content += "\n## 知识来源\n\n"
        for source in sources:
            title = str(source.get("title") or "未记录标题").replace("\n", " ")
            content += f"- {title}；doc={source.get('doc_id')}，chunk={source.get('chunk_id')}，页码={source.get('page_start')}–{source.get('page_end')}。\n"
        if not sources:
            content += "知识库未提供可引用依据；仅有确定性模型与数值检查证据，不能标记工程证据完整。\n"
        report = {"generated": True, "title": "多层导热工程任务报告", "content": content,
                  "content_sha256": hashlib.sha256(content.encode()).hexdigest(), "sections": [{"id": "reference", "title": "模型与交叉验证"}]}
        run = finish_engineering_run(run, {"report": report,
            "retrieval_error": "知识检索未完成。" if retrieval.get("error") else None}, sources)
        # The shared report finalizer appends the execution receipt. Persist and
        # hash that final content, rather than the pre-receipt local string.
        content = report["content"]
        report["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        recorder(run, calculated, content)
        if not recorder.state.get("saved"):
            raise RuntimeError("Reference report checkpoint failed")
        ctx.task["report"] = {key: value for key, value in report.items() if key != "content"}
        response = build_agent_response(answer_text=content, query=ctx.task["query"], task_type="thermal_reference_design",
            task={**analysis.task.to_dict(), "task_type": "thermal_reference_design"}, rewrite=analysis.rewrite.to_dict(), sources=sources,
            session_id=ctx.request["session_id"], metadata={"report": report, "reference_solver": calculated.get("reference_solver"),
                "engineering_run": run, "physics_validation": ctx.task["validation"], "design_review": ctx.task.get("design_review"),
                "calculation": {"used_calculation": good, "tool_name": run["tool_name"], "tool_status": calculated["status"],
                                "tool_inputs": run["input_snapshot"], "tool_result": calculated.get("result") or {}},
                "retrieval_error": "知识检索未完成。" if retrieval.get("error") else None})
        ctx.transition("report", "completed", "导热报告与 SHA-256 已保存，原数值Run可独立追溯。", outputs={"content_sha256": report["content_sha256"]})
        return response
    finally:
        recorder.close()
