"""Non-dominated filtering of compatible measured observations only."""
from __future__ import annotations

from .quality import definition, digest, normalize_boundary

LIMITATIONS = [
    "仅比较已导入且通过本轮机器质量筛查的压降和流量 CV；没有未运行候选性能预测。",
    "数据来源、工况、模型详情、板平面尺寸或收敛准则不同的结果分别分组，无跨组总排序。",
    "非支配筛选仅表示当前观测集中的两个指标关系，不能宣称全局最优或电解效率最优。",
    "网格无关性、实验误差及专业模型仍待验证；重复观测保留，不自动合并。",
]


def compare_results(study, records, result_ids=None):
    if result_ids is not None:
        if not isinstance(result_ids, list) or len(result_ids) != len(set(result_ids)):
            raise ValueError("Distinct result_ids required")
        known = {r["result_id"] for r in records}
        if set(result_ids) - known:
            raise ValueError("Selected results must belong to this study")
        selected = set(result_ids)
        records = [r for r in records if r["result_id"] in selected]
    groups = {}
    excluded = []
    for record in records:
        q = record.get("quality", {})
        obs = record.get("observation", {})
        metrics = q.get("metrics", {})
        if not q.get("eligible_for_comparison") or any(k not in metrics for k in ("pressure_drop_pa", "flow_cv")):
            excluded.append({"result_id": record["result_id"], "candidate_id": record.get("candidate_id"),
                             "provenance": record.get("provenance"), "quality_status": q.get("status"),
                             "reasons": [c for c in q.get("checks", []) if c.get("level") == "error"]})
            continue
        params = (record.get("candidate_snapshot") or {}).get("normalized_parameters", {})
        context = {"physics_model": obs["physics_model"], "model_version": obs["model_version"],
                   "pressure_drop_definition": obs.get("pressure_drop_definition"),
                   "physical_model_details": obs.get("physical_model_details") or {}, "side": obs["side"],
                   "fluid": obs["fluid"], "boundary_conditions_si": normalize_boundary(obs["boundary_conditions"]),
                   "provenance": record["provenance"], "plate_footprint_m": [params.get("plate_width"), params.get("plate_length")],
                   "flow_distribution_basis": obs.get("flow_distribution_basis"),
                   "flow_surface_definition": obs.get("flow_surface_definition") or "parallel_channel_outlets",
                   "mass_balance_scope": obs.get("mass_balance_scope"), "mass_source_kg_s": metrics.get("mass_source_kg_s", 0.0),
                   "convergence_criteria": {k: float(v) for k, v in (obs.get("convergence_criteria") or {}).items()}}
        key = digest(context)
        group = groups.setdefault(key, {"group_id": "pem_group_" + key[:16], "context": context, "results": [],
                                       "pareto_result_ids": []})
        group["results"].append({"result_id": record["result_id"], "candidate_id": record["candidate_id"],
                                 "geometry_version": record.get("geometry_version"), "provenance": record["provenance"],
                                 "quality_status": q["status"], "pressure_drop_pa": metrics["pressure_drop_pa"],
                                 "flow_cv": metrics["flow_cv"], "mesh_id": obs.get("mesh_id"),
                                 "mesh_cells": obs.get("mesh_cells"), "parameters_si": params,
                                 "source_sha256": record["source"]["sha256"]})
    for group in groups.values():
        rows = group["results"]
        for row in rows:
            # Both objectives are minimized; equality does not dominate.
            dominated = any(other["pressure_drop_pa"] <= row["pressure_drop_pa"] and other["flow_cv"] <= row["flow_cv"]
                            and (other["pressure_drop_pa"] < row["pressure_drop_pa"] or other["flow_cv"] < row["flow_cv"])
                            for other in rows)
            row["non_dominated"] = not dominated
            if not dominated:
                group["pareto_result_ids"].append(row["result_id"])
        group["results"] = sorted(rows, key=lambda r: (r["pressure_drop_pa"], r["flow_cv"], r["result_id"]))
        group["sample_count"] = len(rows)
        group["comparison_status"] = "comparable" if len(rows) > 1 else "single_observation"
    return {"version": "pem-comparison-0.1", "observed_only": True,
            "selection_basis": {"objectives": [{"name": "pressure_drop_pa", "direction": "min", "unit": "Pa"},
                                                {"name": "flow_cv", "direction": "min", "unit": "1"}],
                                "method": "pairwise_non_dominated_filter", "prediction_used": False},
            "groups": list(groups.values()), "excluded": excluded, "cross_group_ranking_allowed": False,
            "limitations": LIMITATIONS}
