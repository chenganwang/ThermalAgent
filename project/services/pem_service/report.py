"""Evidence-linked local research report; suggestions do not invent performance."""
from __future__ import annotations

import json
from .quality import definition


def cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ").replace("<", "&lt;").replace(">", "&gt;")


def build_report(study, candidates, records, comparison):
    spec = definition(study)
    lines = ["# PEM 流道初筛研究报告", "", f"研究：{cell(spec.get('title'))}",
             f"研究编号：{cell(study.get('study_id'))}；设定版本：{cell(study.get('study_version', study.get('version')))}。", "",
             "这是工程软件初筛报告。DOE 候选尚待仿真；已导入观测的来源由导入方声明。机器质量筛查不等同于专业模型验收或科学结论。", "",
             f"目标：{cell(spec.get('objective'))}",
             f"研究条件与专业假设：{cell(spec.get('research_conditions', {}))}",
             f"研究者提供的知识引用（未自动审核）：{cell(spec.get('knowledge_sources', []))}",
             f"电极：{cell(spec.get('side'))}；物理类别：{cell(spec.get('physics_model'))}；模型版本：{cell(spec.get('model_version'))}；流体：{cell(spec.get('fluid'))}。", "",
             f"研究设定哈希：{cell(study.get('input_hash', study.get('definition_sha256', '见研究快照')))}。", "",
             "## 参数来源与研究边界", "", "| 参数 | 类型 | 单位 | 研究范围或类别 | 来源 |", "|---|---|---|---|---|"]
    for p in spec.get("parameter_space", []):
        bounds = p.get("choices") if p.get("kind") == "categorical" else [p.get("lower"), p.get("upper")]
        lines.append("| " + " | ".join(cell(v) for v in (p.get("name"), p.get("kind"), p.get("unit"), bounds, p.get("source"))) + " |")
    lines += ["", "用户范围仅作为研究取值空间；本平台未自动设定或证明制造边界。",
              f"边界条件：{cell(spec.get('boundary_conditions'))}",
              f"筛选质量策略：{cell(spec.get('quality_policy') or {'mass_balance_relative_tolerance': 0.01})}（软件初筛容差，需专业组认可）。", "",
              "## 候选生成证据", "", f"保存候选数：{len(candidates)}。每个候选的编号、版本、SI 参数、随机种子及生成版本见 CSV/JSON 导出和工程 Run。", "",
              "| 候选编号 | 几何版本 | DOE 批次 | 参数 SI |", "|---|---|---|---|"]
    for c in candidates:
        lines.append("| " + " | ".join(cell(v) for v in (c["candidate_id"], c.get("geometry_version"), c.get("batch_id"), c.get("normalized_parameters"))) + " |")
    lines += ["", "## 原始观测与质量", "", "| 结果编号 | 候选 | 来源标签 | 文件与行号 | SHA256 | 求解状态 | 质量 |", "|---|---|---|---|---|---|---|"]
    for r in records:
        src, obs = r["source"], r.get("observation", {})
        lines.append("| " + " | ".join(cell(v) for v in (r["result_id"], r.get("candidate_id"), r["provenance"],
                     f"{src['filename']} : {src['row_number']}", src["sha256"], obs.get("convergence_status"), r["quality"]["status"])) + " |")
    if any(r["provenance"] == "synthetic_demo" for r in records):
        lines += ["", "**本报告包含 synthetic_demo 合成演示数据，不得作为真实 Fluent 结果、科研性能或实验验收。**"]
    for r in records:
        errors = [c for c in r["quality"]["checks"] if c["level"] == "error"]
        if errors:
            lines += ["", f"结果 {cell(r['result_id'])} 已保留但排除比较："]
            lines += [f"- {cell(c['code'])}：{cell(c['message'])}" for c in errors]
    lines += ["", "## 同工况观测比较", "", "压降和 CV 越低越好。每组单独做非支配筛选；不跨来源、工况或模型总排序。"]
    for group in comparison["groups"]:
        lines += ["", f"### 比较组 {group['group_id']}", "", f"条件：{cell(group['context'])}", "",
                  "| 结果 | 候选 | 压降 Pa | 总质量流量 CV | 当前观测集非支配 |", "|---|---|---|---|---|"]
        for r in group["results"]:
            lines.append("| " + " | ".join(cell(v) for v in (r["result_id"], r["candidate_id"],
                         format(r["pressure_drop_pa"], ".8g"), format(r["flow_cv"], ".8g"), "是" if r["non_dominated"] else "否")) + " |")
    if not comparison["groups"]:
        lines += ["", "当前没有符合比较条件的观测；不生成性能排序。"]
    lines += ["", "## 验证限制", ""] + ["- " + text for text in comparison["limitations"]]
    lines += ["", "## 下一轮建议", ""]
    if any(not r["quality"]["eligible_for_comparison"] for r in records):
        lines.append("- 先补充缺失字段、修正单位和工况绑定，并对失败或未收敛算例重新求解；旧失败记录继续保留。")
    observed = {r["candidate_id"] for r in records if r["quality"]["eligible_for_comparison"]}
    pending = [c["candidate_id"] for c in candidates if c["candidate_id"] not in observed]
    if pending:
        lines.append(f"- 尚有 {len(pending)} 个候选无合格观测。可在专业组核准几何和物理模型后安排下一轮仿真；此清单按候选记录列出，不预测改善幅度。")
    lines += ["- 对当前非支配观测补做独立网格加密和重复求解，核对 case/data、质量流量面定义、压降取面与残差日志。",
              "- 向专业组确认两相/电化学模型、相物性、边界和验证算例后，再规划 PyFluent、代理模型、敏感性及多目标优化。",
              "- 单相水力指标只能支撑相应流动研究，不能推断电解效率、产氢性能或耐久性。", ""]
    return "\n".join(lines)
