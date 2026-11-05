from __future__ import annotations

from typing import Any
from math import isfinite


DEFAULT_GRAPH_WARNINGS = [
    "该图为一级示意图。",
    "该图为工程解释图，不是 CFD 仿真云图。",
    "该图不替代 CFD。",
    "该图不包含详细流道、压降或泵曲线。",
    "该图不能作为工业级设计图。"
]

DEFAULT_GRAPH_LIMITATIONS = [
    "该图为工程解释图，不是 CFD 仿真云图。",
    "节点参数为空时表示当前问题未提供或知识库未检索到。",
    "generic_template=true 时表示使用通用模板，不代表真实机柜或冷板模型。",
    "simulation_based=false 时表示未运行 CFD 或外部仿真求解器。",
]

_NODE_HINTS: dict[str, dict[str, Any]] = {
    "heat_source": {
        "role": "产生热量",
        "parameters": [{"name": "功耗", "symbol": "P", "unit": "W", "value": None, "source": "unknown"}],
        "risks": ["功耗过高导致结温超过限制。", "热流密度过高导致局部热点。"],
        "frontend_hint": {"display_group": "热源", "icon": "chip", "emphasis": "high"},
    },
    "thermal_interface": {
        "role": "降低芯片与冷板之间的界面热阻",
        "parameters": [{"name": "界面热阻", "symbol": "R_TIM", "unit": "K/W", "value": None, "source": "unknown"}],
        "risks": ["TIM 厚度过大。", "接触压力不足导致接触热阻偏高。"],
        "frontend_hint": {"display_group": "导热界面", "icon": "layers", "emphasis": "medium"},
    },
    "interface_resistance": {
        "role": "表示导热界面和接触热阻",
        "parameters": [{"name": "界面热阻", "symbol": "R_contact", "unit": "K/W", "value": None, "source": "unknown"}],
        "risks": ["界面材料老化或装配不均会放大热阻。"],
        "frontend_hint": {"display_group": "导热界面", "icon": "layers", "emphasis": "medium"},
    },
    "heat_spreader": {
        "role": "扩散热量并传递给冷却侧",
        "parameters": [{"name": "等效热阻", "symbol": "R", "unit": "K/W", "value": None, "source": "unknown"}],
        "risks": ["扩散热阻偏高。", "冷板接触面积不足。"],
        "frontend_hint": {"display_group": "换热部件", "icon": "panel-top", "emphasis": "medium"},
    },
    "heat_exchanger": {
        "role": "在固体壁面与冷却介质之间换热",
        "parameters": [{"name": "换热能力", "symbol": "UA", "unit": "W/K", "value": None, "source": "unknown"}],
        "risks": ["换热能力不足。", "内部流道堵塞或分配不均。"],
        "frontend_hint": {"display_group": "换热部件", "icon": "panel-top", "emphasis": "medium"},
    },
    "fluid": {
        "role": "吸收并输运热量",
        "parameters": [{"name": "体积流量", "symbol": "V_dot", "unit": "L/min", "value": None, "source": "unknown"}],
        "risks": ["流量不足导致温升过大。", "冷却液物性未确认。"],
        "frontend_hint": {"display_group": "冷却液", "icon": "droplet", "emphasis": "medium"},
    },
    "convective_boundary": {
        "role": "表示冷板到冷却液的对流换热边界",
        "parameters": [{"name": "对流热阻", "symbol": "R_conv", "unit": "K/W", "value": None, "source": "unknown"}],
        "risks": ["流道换热不足。", "局部流速不足导致热点。"],
        "frontend_hint": {"display_group": "对流边界", "icon": "waves", "emphasis": "medium"},
    },
    "distribution_unit": {
        "role": "分配、监测并连接设施侧换热",
        "parameters": [{"name": "供液能力", "symbol": "Q_cdu", "unit": "W", "value": None, "source": "unknown"}],
        "risks": ["CDU 能力不足。", "监测或控制策略未确认。"],
        "frontend_hint": {"display_group": "CDU", "icon": "server", "emphasis": "medium"},
    },
    "pump": {
        "role": "提供冷却液循环所需压头",
        "parameters": [{"name": "扬程/压头", "symbol": "H", "unit": "m", "value": None, "source": "unknown"}],
        "risks": ["泵曲线未匹配。", "目标流量下压降未校核。"],
        "frontend_hint": {"display_group": "泵", "icon": "rotate-cw", "emphasis": "high"},
    },
    "pipe": {
        "role": "连接液冷回路并输运冷却液",
        "parameters": [{"name": "管路压降", "symbol": "Delta_p", "unit": "kPa", "value": None, "source": "unknown"}],
        "risks": ["管路压降未校核。", "接头泄漏风险未评估。"],
        "frontend_hint": {"display_group": "管路", "icon": "route", "emphasis": "low"},
    },
    "heat_rejection": {
        "role": "把系统热量排向设施侧或环境",
        "parameters": [{"name": "排热能力", "symbol": "Q_reject", "unit": "W", "value": None, "source": "unknown"}],
        "risks": ["设施侧换热能力不足。", "外部冷源边界条件未确认。"],
        "frontend_hint": {"display_group": "排热", "icon": "wind", "emphasis": "medium"},
    },
}

_NODE_TYPE_ALIASES = {
    "cold_plate": "heat_exchanger",
    "coolant": "fluid",
    "coolant_loop": "fluid",
    "cdu": "distribution_unit",
    "ambient": "heat_rejection",
    "solid_layer": "heat_spreader",
    "manifold": "pipe",
    "return_manifold": "pipe",
    "branch_loop": "pipe",
    "air_inlet_zone": "fluid",
    "air_inlet": "fluid",
    "heat_pickup": "heat_exchanger",
    "air_outlet": "fluid",
    "air_exhaust_zone": "heat_rejection",
}

_EDGE_TYPE_ALIASES = {
    "conduction": "conduction",
    "contact_conduction": "conduction",
    "r_package": "conduction",
    "r_tim_contact": "conduction",
    "r_cold_plate": "conduction",
    "r_convective": "convection",
    "convection": "convection",
    "forced_convection": "convection",
    "fluid_transport": "fluid_transport",
    "fluid_supply": "fluid_transport",
    "fluid_distribution": "fluid_transport",
    "distribution": "fluid_transport",
    "branch_flow": "fluid_transport",
    "heated_return": "fluid_transport",
    "heat_transport": "heat_rejection",
    "heat_rejection": "heat_rejection",
    "exhaust": "heat_rejection",
    "airflow": "fluid_transport",
    "heated_airflow": "fluid_transport",
    "loop_closure": "control_or_monitoring",
    "loop_control": "control_or_monitoring",
}

_EDGE_HINTS = {
    "conduction": {
        "direction": "heat_flow",
        "parameters": [{"name": "热阻", "symbol": "R", "unit": "K/W", "value": None, "source": "unknown"}],
        "risks": ["接触热阻偏高。", "导热路径过长或材料导热系数不足。"],
        "frontend_hint": {"line_style": "solid", "emphasis": "medium"},
    },
    "convection": {
        "direction": "heat_flow",
        "parameters": [{"name": "对流换热系数", "symbol": "h", "unit": "W/(m2*K)", "value": None, "source": "unknown"}],
        "risks": ["局部流速不足。", "换热面积或流道分配未确认。"],
        "frontend_hint": {"line_style": "solid", "emphasis": "medium"},
    },
    "fluid_transport": {
        "direction": "coolant_flow",
        "parameters": [{"name": "流量", "symbol": "V_dot", "unit": "L/min", "value": None, "source": "unknown"}],
        "risks": ["流量不足。", "支路不均流或管路阻力未校核。"],
        "frontend_hint": {"line_style": "dashed", "emphasis": "medium"},
    },
    "heat_rejection": {
        "direction": "heat_flow",
        "parameters": [{"name": "排热量", "symbol": "Q", "unit": "W", "value": None, "source": "unknown"}],
        "risks": ["设施侧冷源能力不足。", "换热器运行边界未确认。"],
        "frontend_hint": {"line_style": "solid", "emphasis": "medium"},
    },
    "control_or_monitoring": {
        "direction": "control_loop",
        "parameters": [],
        "risks": ["控制策略、监测点和告警阈值未定义。"],
        "frontend_hint": {"line_style": "dotted", "emphasis": "low"},
    },
}


def _copy_parameters(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in values if isinstance(item, dict)]


def _node_hint(node_type: str) -> dict[str, Any]:
    normalized = _NODE_TYPE_ALIASES.get(str(node_type or ""), str(node_type or ""))
    return _NODE_HINTS.get(
        normalized,
        {
            "role": "参与散热路径",
            "parameters": [],
            "risks": [],
            "frontend_hint": {"display_group": "其他", "icon": "circle", "emphasis": "low"},
        },
    )


def _edge_type(mechanism: str) -> str:
    key = str(mechanism or "").strip().lower()
    return _EDGE_TYPE_ALIASES.get(key, "control_or_monitoring" if "control" in key else "fluid_transport")


def _edge_hint(edge_type: str) -> dict[str, Any]:
    return _EDGE_HINTS.get(edge_type, _EDGE_HINTS["fluid_transport"])


def _graph_quality(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, bool]:
    node_required = ("id", "label", "type", "role", "description", "risks", "frontend_hint")
    edge_required = ("source", "target", "label", "type", "direction", "description", "risks", "frontend_hint")
    return {
        "has_nodes": bool(nodes),
        "has_edges": bool(edges),
        "has_engineering_parameters": any(bool(item.get("engineering_parameters")) for item in [*nodes, *edges]),
        # The legacy field above means parameter slots exist, not measured values.
        "has_numeric_parameters": any(
            isinstance(parameter.get("value"), (int, float))
            and not isinstance(parameter.get("value"), bool) and isfinite(parameter["value"])
            for item in [*nodes, *edges] for parameter in item.get("engineering_parameters", [])
        ),
        "has_risks": any(bool(item.get("risks")) for item in [*nodes, *edges]),
        "frontend_ready": bool(nodes)
        and bool(edges)
        and all(all(key in node for key in node_required) for node in nodes)
        and all(all(key in edge for key in edge_required) for edge in edges),
    }


def make_node(
    node_id: str,
    label: str,
    node_type: str,
    description: str,
    *,
    role: str | None = None,
    engineering_parameters: list[dict[str, Any]] | None = None,
    risks: list[str] | None = None,
    frontend_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hint = _node_hint(node_type)
    return {
        "id": node_id,
        "label": label,
        "type": node_type,
        "role": role or str(hint.get("role") or "参与散热路径"),
        "description": description,
        "engineering_parameters": _copy_parameters(engineering_parameters if engineering_parameters is not None else hint.get("parameters") or []),
        "risks": list(risks if risks is not None else hint.get("risks") or []),
        "frontend_hint": dict(frontend_hint or hint.get("frontend_hint") or {}),
    }


def make_edge(
    source: str,
    target: str,
    mechanism: str,
    label: str,
    description: str,
    *,
    edge_id: str | None = None,
    edge_type: str | None = None,
    direction: str | None = None,
    engineering_parameters: list[dict[str, Any]] | None = None,
    risks: list[str] | None = None,
    frontend_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = edge_type or _edge_type(mechanism)
    hint = _edge_hint(normalized_type)
    return {
        "id": edge_id or f"{source}_to_{target}",
        "source": source,
        "target": target,
        "mechanism": mechanism,
        "type": normalized_type,
        "direction": direction or str(hint.get("direction") or "heat_flow"),
        "label": label,
        "description": description,
        "engineering_parameters": _copy_parameters(engineering_parameters if engineering_parameters is not None else hint.get("parameters") or []),
        "risks": list(risks if risks is not None else hint.get("risks") or []),
        "frontend_hint": dict(frontend_hint or hint.get("frontend_hint") or {}),
    }


def make_graph(
    *,
    graph_type: str,
    title: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    source_based: bool = False,
    generic_template: bool = True,
    simulation_based: bool = False,
    warnings: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    warning_values = list(warnings or DEFAULT_GRAPH_WARNINGS)
    limitation_values = list(limitations or DEFAULT_GRAPH_LIMITATIONS)
    return {
        "graph_type": graph_type,
        "title": title,
        "nodes": nodes,
        "edges": edges,
        "warnings": warning_values,
        "limitations": limitation_values,
        "source_based": bool(source_based),
        "generic_template": bool(generic_template),
        "simulation_based": bool(simulation_based),
        "graph_quality": _graph_quality(nodes, edges),
    }
