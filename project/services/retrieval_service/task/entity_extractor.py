from __future__ import annotations

import re

from ..domain_rules import ashrae_rules
from .normalizer import normalize_query


_THERMAL_ENTITIES: dict[str, tuple[str, ...]] = {
    "CPU": ("cpu",),
    "GPU": ("gpu",),
    "ASHRAE": ("ashrae",),
    "OCP": ("ocp", "open compute project"),
    "A1": ("a1",),
    "A2": ("a2",),
    "A3": ("a3",),
    "A4": ("a4",),
    "H1": ("h1",),
    "W17": ("w17",),
    "W27": ("w27",),
    "W32": ("w32",),
    "W40": ("w40",),
    "W45": ("w45",),
    "W+": ("w+", "w plus", "w-plus"),
    "干球温度": ("干球温度", "dry-bulb", "dry bulb"),
    "供水温度": ("供水温度", "water supply temperature", "facility water supply"),
    "液冷等级": ("液冷等级", "liquid cooling class"),
    "AI服务器": ("ai服务器", "ai server", "ai servers"),
    "服务器": ("服务器", "server", "servers"),
    "数据中心": ("数据中心", "data center", "datacenter"),
    "液冷": ("液冷", "liquid cooling", "liquid-cooled"),
    "风冷": ("风冷", "air cooling", "air-cooled"),
    "空气冷却": ("空气冷却", "air cooling"),
    "冷板": ("冷板", "cold plate", "cooling plate"),
    "CDU": ("cdu", "coolant distribution unit"),
    "冷却液": ("冷却液", "coolant"),
    "水": ("水", "water"),
    "乙二醇水溶液": ("乙二醇", "乙二醇水溶液", "ethylene glycol", "ethylene glycol water", "egw"),
    "丙二醇水溶液": ("丙二醇", "丙二醇水溶液", "propylene glycol", "propylene glycol water", "pgw"),
    "热阻": ("热阻", "thermal resistance"),
    "流道": ("流道", "channel", "flow channel"),
    "管路": ("管路", "管道", "水管", "pipe", "piping", "hose"),
    "泵": ("泵", "pump"),
    "换热器": ("换热器", "heat exchanger"),
    "芯片": ("芯片", "chip"),
    "结温": ("结温", "junction temperature"),
    "温升": ("温升", "temperature rise"),
    "热负荷": ("热负荷", "发热量", "heat load", "thermal load"),
    "流量": ("流量", "质量流量", "体积流量", "flow rate", "mass flow"),
    "热通量": ("热通量", "heat flux"),
    "压降": ("压降", "压力损失", "pressure drop", "delta p"),
    "导热": ("导热", "conduction"),
    "对流": ("对流", "convection"),
    "辐射": ("辐射", "radiation"),
    "TIM": ("tim", "thermal interface material", "导热界面材料"),
    "PUE": ("pue",),
    "TDP": ("tdp",),
}


def extract_entities(query: str) -> list[str]:
    """Extract a small set of thermal-management and ASHRAE entities."""

    normalized = normalize_query(query)
    lowered = normalized.lower()
    entities: list[str] = []
    for canonical, aliases in _THERMAL_ENTITIES.items():
        if any(alias.lower() in lowered for alias in aliases):
            entities.append(canonical)
    if re.search(r"A1\s*(?:到|至|-|to|through)\s*A4", normalized, re.IGNORECASE):
        for item in ("A1", "A2", "A3", "A4"):
            if item not in entities:
                entities.append(item)
    return ashrae_rules.append_entities(normalized, entities)
