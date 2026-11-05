from __future__ import annotations

import re


TERM_EXPANSIONS: dict[str, list[str]] = {
    "GPU": ["GPU", "graphics processing unit", "accelerator", "高功率芯片", "AI加速卡"],
    "CPU": ["CPU", "processor", "server processor", "中央处理器"],
    "服务器": ["服务器", "server", "rack", "机柜", "数据中心"],
    "AI服务器": ["AI服务器", "AI server", "GPU server", "高密度服务器", "high-density servers"],
    "数据中心": ["数据中心", "data center", "datacenter", "PUE", "机房"],
    "液冷": ["液冷", "liquid cooling", "cold plate", "冷板", "CDU", "冷却液"],
    "风冷": ["风冷", "air cooling", "空气冷却", "heat sink", "fan", "风道"],
    "空气冷却": ["空气冷却", "air cooling", "Thermal Guidelines for Air Cooling"],
    "冷板": ["冷板", "cold plate", "microchannel cold plate", "流道", "均温"],
    "CDU": ["CDU", "coolant distribution unit", "冷量分配单元", "二次侧"],
    "冷却液": ["冷却液", "coolant", "water glycol", "乙二醇水溶液"],
    "热阻": ["热阻", "thermal resistance", "Rth", "热路径", "界面热阻"],
    "结温": ["结温", "junction temperature", "Tj", "芯片温度"],
    "温升": ["温升", "temperature rise", "delta T", "热负载"],
    "热通量": ["热通量", "heat flux", "W/cm2", "高热流密度"],
    "导热": ["导热", "heat conduction", "thermal conductivity", "傅里叶定律"],
    "对流": ["对流", "convection", "heat transfer coefficient", "换热系数"],
    "辐射": ["辐射", "radiation", "emissivity", "热辐射"],
    "TIM": ["TIM", "thermal interface material", "导热界面材料", "导热硅脂"],
    "PUE": ["PUE", "power usage effectiveness", "数据中心能效"],
    "ASHRAE": ["ASHRAE", "Thermal Guidelines for Data Processing Environments", "thermal guidelines"],
    "干球温度": ["干球温度", "dry-bulb temperature", "dry bulb temperature", "DryBulb Temp."],
    "推荐": ["推荐", "recommended"],
    "允许": ["允许", "allowable"],
    "湿度": ["湿度", "humidity", "RH", "relative humidity"],
    "露点": ["露点", "dew point", "DP"],
    "供水温度": ["供水温度", "facility water supply temperature", "water supply temperature"],
    "液冷等级": ["液冷等级", "liquid cooling class", "W17 W27 W32 W40 W45 W+"],
    "高密度服务器": ["高密度服务器", "high-density servers", "H1"],
    "A1": ["A1"],
    "A2": ["A2"],
    "A3": ["A3"],
    "A4": ["A4"],
    "H1": ["H1", "high-density server", "high-density servers"],
    "W17": ["W17", "liquid cooling class W17"],
    "W27": ["W27", "liquid cooling class W27"],
    "W32": ["W32", "liquid cooling class W32"],
    "W40": ["W40", "liquid cooling class W40"],
    "W45": ["W45", "liquid cooling class W45"],
    "W+": ["W+", "liquid cooling class W+"],
}


TASK_KEYWORDS: dict[str, list[str]] = {
    "concept_explanation": ["定义", "作用", "关键机制", "热管理"],
    "mechanism_analysis": ["机理", "传热路径", "影响因素", "热管理"],
    "comparison": ["对比", "优缺点", "适用场景", "数据中心"],
    "troubleshooting": ["异常", "原因", "排查", "影响因素"],
    "design_advice": ["设计", "选型", "约束", "风险点", "工程案例"],
    "literature_lookup": ["来源", "章节", "页码", "资料"],
    "general_qa": [],
}


def dedupe(items: list[str], *, max_items: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = re.sub(r"\s+", " ", (item or "").strip())
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if max_items is not None and len(out) >= max_items:
            break
    return out


def keywords_from_query(query: str, *, max_items: int = 18) -> list[str]:
    english = re.findall(r"[A-Za-z][A-Za-z0-9_+./-]*", query or "")
    cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,}", query or "")
    return dedupe([*english, *cjk_terms], max_items=max_items)


def expand_terms(entities: list[str], query: str, *, max_items: int = 32) -> list[str]:
    """Expand known thermal and ASHRAE terms into Chinese and English tokens."""

    lowered = (query or "").lower()
    terms: list[str] = []
    for entity in entities:
        terms.extend(TERM_EXPANSIONS.get(entity, [entity]))
    for canonical, expansions in TERM_EXPANSIONS.items():
        if canonical.lower() in lowered:
            terms.extend(expansions)
    return dedupe(terms, max_items=max_items)


def task_keywords(task_type: str, *, max_items: int | None = None) -> list[str]:
    return dedupe(TASK_KEYWORDS.get(task_type or "general_qa", []), max_items=max_items)
