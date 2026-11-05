from __future__ import annotations

import re
from typing import Any

from .property_schemas import (
    FluidPropertyLookupResult,
    PROPERTY_STATUS_EXACT,
    PROPERTY_STATUS_INTERPOLATED,
    PROPERTY_STATUS_MISSING_DATA,
    PROPERTY_STATUS_MISSING_PARAMS,
    PROPERTY_STATUS_UNSUPPORTED_FLUID,
    PROPERTY_STATUS_UNSUPPORTED_PROPERTY,
    PROPERTY_STATUS_UNSUPPORTED_RANGE,
)
from .property_store import FluidPropertyStore, get_default_property_store, normalize_fluid_name, normalize_property_name


_TEMPERATURE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°\s*C|℃|deg\s*C|degC|\bC\b)", re.IGNORECASE)
_CONCENTRATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:wt\s*%|vol\s*%|%)", re.IGNORECASE)


def parse_property_query(query: str) -> dict[str, Any]:
    text = str(query or "")
    temperature_match = _TEMPERATURE_RE.search(text)
    concentration_match = _CONCENTRATION_RE.search(text)
    return {
        "query": text,
        "fluid": normalize_fluid_name(text),
        "property_name": normalize_property_name(text),
        "temperature_c": None if temperature_match is None else float(temperature_match.group(1)),
        "concentration_percent": None if concentration_match is None else float(concentration_match.group(1)),
    }


def lookup_property_from_query(
    query: str,
    *,
    store: FluidPropertyStore | None = None,
    allow_interpolation: bool = True,
) -> FluidPropertyLookupResult:
    parsed = parse_property_query(query)
    active = store or get_default_property_store()
    return active.lookup(
        str(parsed.get("fluid") or ""),
        str(parsed.get("property_name") or ""),
        temperature_c=parsed.get("temperature_c"),
        concentration_percent=parsed.get("concentration_percent"),
        allow_interpolation=allow_interpolation,
    )


def answer_property_query(result: FluidPropertyLookupResult | dict[str, Any]) -> str:
    data = result.to_dict() if isinstance(result, FluidPropertyLookupResult) else dict(result or {})
    status = str(data.get("status") or "failed")
    fluid = data.get("normalized_fluid") or data.get("fluid") or "未指定流体"
    prop = data.get("normalized_property_name") or data.get("property_name") or "未指定物性"
    temperature = data.get("temperature_c")
    concentration = data.get("concentration_percent")
    context = f"{fluid} 的 {prop}"
    if temperature is not None:
        context += f"（{temperature} °C）"
    if concentration is not None:
        context += f"，浓度 {concentration}%"

    if status in {PROPERTY_STATUS_EXACT, PROPERTY_STATUS_INTERPOLATED, "success"}:
        value = data.get("value")
        unit = data.get("unit") or ""
        source = data.get("source") or {}
        source_status = source.get("source_status") or source.get("source_quality") or "unknown"
        lines = [f"结构化物性查询结果：{context} = {value} {unit}。"]
        if data.get("pressure_condition"):
            lines.append(f"压力/状态条件：{data.get('pressure_condition')}。")
        if status == PROPERTY_STATUS_INTERPOLATED or data.get("interpolation"):
            lines.append("插值方式：仅在已有温度点之间做一维线性插值；未做外推。")
        source_title = source.get("source_title") or source.get("source_name") or source.get("source_id")
        if source_title:
            lines.append(f"来源：{source_title}；source_status={source_status}。")
        warnings = [str(item) for item in data.get("warnings") or [] if item]
        if warnings:
            lines.append("注意：" + "；".join(warnings) + "。")
        return "\n".join(lines)

    if status == PROPERTY_STATUS_MISSING_PARAMS:
        missing = ", ".join(str(item) for item in data.get("missing_fields") or []) or "unknown"
        return f"结构化物性查询无法执行：{context} 缺少必要输入 {missing}。混合液需要浓度；物性表查询需要温度。"

    if status == PROPERTY_STATUS_MISSING_DATA:
        return (
            f"结构化物性查询结论：status=missing_data，本地正式物性层没有 {context} 的可靠数值，因此不返回数值。\n"
            "边界：ThermalAgent 不会从无关液冷 chunk 中拼出物性值，也不会自动把水的默认值套用到乙二醇/丙二醇或空气。"
        )

    if status == PROPERTY_STATUS_UNSUPPORTED_RANGE:
        supported = data.get("supported_range")
        return f"结构化物性查询结论：{context} 超出本地数据支持范围，不做外推。supported_range={supported}。"

    if status == PROPERTY_STATUS_UNSUPPORTED_FLUID:
        return f"结构化物性查询结论：当前本地物性层不支持该流体：{data.get('fluid') or fluid}。"

    if status == PROPERTY_STATUS_UNSUPPORTED_PROPERTY:
        return f"结构化物性查询结论：当前本地物性层不支持该物性：{data.get('property_name') or prop}。"

    return f"结构化物性查询失败：{data.get('error') or status}。"


__all__ = ["answer_property_query", "lookup_property_from_query", "parse_property_query"]
