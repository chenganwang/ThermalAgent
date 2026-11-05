"""Evaluate explicit design limits against recorded numbers, without a model judge."""
import math

METRICS = {
    "max_pressure_drop_pa": ("pressure_drop_pa", "Pa", "管路压降", False),
    "max_volume_flow_l_min": ("volume_flow_L_min", "L/min", "所需体积流量", False),
    "max_thermal_resistance_k_w": ("equivalent_resistance", "K/W", "总热阻", False),
    "max_heat_rate_abs_w": ("heat_rate", "W", "传热量绝对值", True),
}


def evaluate_design(criteria, measured):
    checks = []
    for criterion, maximum in criteria.items():
        if maximum is None:
            continue
        metric, unit, label, magnitude = METRICS[criterion]
        value = measured.get(metric)
        available = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        actual = (abs(value) if magnitude else value) if available else None
        status = "unavailable" if not available else "passed" if actual <= maximum else "violated"
        checks.append({"criterion": criterion, "metric": metric, "label": label, "unit": unit,
                       "actual": actual, "maximum": maximum, "margin": maximum - actual if available else None,
                       "status": status, "source": "recorded_tool_output" if available else "not_recorded"})
    status = "unavailable" if any(c["status"] == "unavailable" for c in checks) else "violated" if any(c["status"] == "violated" for c in checks) else "passed"
    return {"reviewer_version": "explicit-design-limits-v1", "method": "deterministic_recorded_output_limits",
            "status": status, "passed": bool(checks) and status == "passed", "checks": checks,
            "limitations": ["仅判断显式上限与本模型实际输出；不等同实验、制造适用性或系统级设计认证。"]}


def run_design_review(ctx, measured):
    criteria = ctx.request.get("design_criteria")
    if not criteria:
        return None
    ctx.transition("design_review", "running", "将已保存的计算结果与用户显式工程上限比较。", inputs=criteria,
                   tool_name="explicit_design_limits", tool_version="explicit-design-limits-v1")
    review = evaluate_design(criteria, measured)
    ctx.task["design_review"] = review
    ctx.transition("design_review", "completed" if review["passed"] else "incomplete",
                   "已满足本次声明的设计上限。" if review["passed"] else "设计上限未满足或缺少对应输出；保留物理检查及实际计算。", outputs=review)
    if not review["passed"] and ctx.task.get("outcome") == "completed":
        ctx.task["outcome"] = "incomplete"
    return review


def design_review_markdown(review):
    if not review:
        return ""
    lines = ["", "## 设计指标检查", "", "设计达标与物理一致性分别记录。", "",
             "| 指标 | 实际值 | 上限 | 单位 | 结论 |", "|---|---|---|---|---|"]
    for check in review["checks"]:
        actual = check["actual"] if check["actual"] is not None else "未记录"
        lines.append(f"| {check['label']} | {actual} | {check['maximum']} | {check['unit']} | {check['status']} |")
    if not review["passed"]:
        lines += ["", "本方案尚未满足全部声明指标。请修订几何、边界条件或设计目标后新建关联任务，不能将其作为已达标方案。"]
    return "\n".join(lines) + "\n"
