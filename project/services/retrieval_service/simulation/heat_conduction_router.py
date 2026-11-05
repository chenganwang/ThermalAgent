from __future__ import annotations

from typing import Any

from ..tools.unit_parser import (
    normalize_text,
    parse_area_m2,
    parse_cold_temperature_c,
    parse_conductivity_w_mk,
    parse_hot_temperature_c,
    parse_thickness_m,
)


HEAT_CONDUCTION_DEMO_NAME = "heat_conduction_1d"
HEAT_CONDUCTION_PARAMETER_NAMES = (
    "length_m",
    "thermal_conductivity_w_mk",
    "area_m2",
    "t_hot_c",
    "t_cold_c",
)


def parse_heat_conduction_1d_inputs(query: str) -> dict[str, Any]:
    text = normalize_text(query or "")
    params = {
        "length_m": parse_thickness_m(text),
        "thermal_conductivity_w_mk": parse_conductivity_w_mk(text),
        "area_m2": parse_area_m2(text),
        "t_hot_c": parse_hot_temperature_c(text),
        "t_cold_c": parse_cold_temperature_c(text),
    }
    missing = [name for name in HEAT_CONDUCTION_PARAMETER_NAMES if params[name] is None]
    invalid = [
        name
        for name in ("length_m", "thermal_conductivity_w_mk", "area_m2")
        if params[name] is not None and float(params[name]) <= 0
    ]
    return {
        "params": params,
        "missing_parameters": missing,
        "invalid_parameters": invalid,
    }


def is_heat_conduction_1d_request(query: str) -> bool:
    text = normalize_text(query or "")
    lowered = text.lower()
    strong_terms = ("平壁", "一维导热", "一维稳态导热", "稳态导热", "plane wall", "one-dimensional conduction")
    parameter_terms = ("厚度", "导热系数", "传热面积", "面积", "热端", "冷端", "t_hot", "t_cold")
    strong = any(term in lowered for term in strong_terms)
    semantic_count = sum(1 for term in parameter_terms if term in lowered)
    parsed = parse_heat_conduction_1d_inputs(text)
    parsed_count = sum(value is not None for value in parsed["params"].values())
    return bool(strong and (semantic_count >= 2 or parsed_count >= 3))


def build_heat_conduction_1d_route(query: str) -> dict[str, Any]:
    parsed = parse_heat_conduction_1d_inputs(query)
    missing = list(parsed["missing_parameters"])
    invalid = list(parsed["invalid_parameters"])
    if missing:
        status = "missing_parameters"
        message = "请补充缺少的一维导热参数，并在结构化表单中确认。"
    elif invalid:
        status = "invalid_parameters"
        message = "一维导热参数非法：厚度、面积和导热系数必须大于 0。"
    else:
        status = "input_confirmation_required"
        message = "已识别一维平壁稳态导热参数；请确认后通过受控 MATLAB demo 运行。"
    return {
        "enabled": True,
        "route": HEAT_CONDUCTION_DEMO_NAME,
        "task_type": HEAT_CONDUCTION_DEMO_NAME,
        "stage": "heat_conduction_1d_input_confirmation",
        "status": status,
        "simulation_ready": False,
        "demo_name": HEAT_CONDUCTION_DEMO_NAME,
        "endpoint": "/simulation/matlab/demo",
        "params": dict(parsed["params"]),
        "missing_parameters": missing,
        "invalid_parameters": invalid,
        "model_file": None,
        "cfd_executed": False,
        "message": message,
    }


__all__ = [
    "HEAT_CONDUCTION_DEMO_NAME",
    "HEAT_CONDUCTION_PARAMETER_NAMES",
    "build_heat_conduction_1d_route",
    "is_heat_conduction_1d_request",
    "parse_heat_conduction_1d_inputs",
]
