from __future__ import annotations

from typing import Any, Mapping


_REQUIRED_CONDITIONS = [
    "热源分布",
    "进风/进水温度",
    "冷却方式",
    "风量或液冷流量",
    "材料参数",
    "边界条件",
]

_CONDITION_ALIASES: dict[str, tuple[str, ...]] = {
    "热源分布": ("heat_source_distribution", "heat_loads", "热源分布", "热负荷分布"),
    "进风/进水温度": ("inlet_temperature", "air_inlet_temperature", "water_inlet_temperature", "入口温度", "进风温度", "进水温度"),
    "冷却方式": ("cooling_method", "冷却方式"),
    "风量或液冷流量": ("airflow", "flow_rate", "coolant_flow", "liquid_flow_rate", "风量", "液冷流量", "冷却流量"),
    "材料参数": ("material_properties", "materials", "材料参数", "材料导热系数"),
    "边界条件": ("boundary_conditions", "boundaries", "边界条件"),
}


def _has_condition(conditions: Mapping[str, Any], label: str) -> bool:
    aliases = _CONDITION_ALIASES[label]
    lowered = {str(key).lower(): value for key, value in conditions.items()}
    for alias in aliases:
        value = lowered.get(alias.lower())
        if value not in (None, "", [], {}):
            return True
    return False


def check_simulation_readiness(model_file: dict[str, Any], conditions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    values = dict(conditions or {})
    available = []
    if model_file:
        available.append("机柜几何模型" if model_file.get("object_type") == "rack_cabinet" else "几何模型")

    missing = []
    for label in _REQUIRED_CONDITIONS:
        if _has_condition(values, label):
            available.append(label)
        else:
            missing.append(label)

    return {
        "simulation_ready": False,
        "model_file": dict(model_file or {}),
        "available_conditions": available,
        "required_conditions": list(_REQUIRED_CONDITIONS),
        "missing_conditions": missing,
        "next_action": "补充边界条件后生成仿真任务文件",
        "stage": "simulation_preparation_stub",
        "warnings": [
            "simulation_ready=false 是当前阶段的正常结果。",
            "当前不运行 CFD。",
            "当前不输出仿真数值结果。",
            "当前只做仿真任务准备和缺参检查。",
        ],
    }
