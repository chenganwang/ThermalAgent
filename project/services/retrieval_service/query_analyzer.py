from __future__ import annotations

import re
from typing import Callable

from .config import AppConfig
from .query_types import QueryPlan


_REF_PAT = re.compile(r"(?:图|表)\s*\d+(?:\s*[-－–\.]\s*\d+)*|第\s*[一二三四五六七八九十百千万0-9]+\s*[章节]|式\s*\(?\s*\d+(?:\s*[-－–\.]\s*\d+)*\s*\)?")
_NUMUNIT_PAT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:℃|°C|K|W|kW|L/min|LPM|kg/s|MPa|kPa|Pa|bar|kg/m3|kg/m\^3|"
    r"W/m2K|W/\(m·K\)|m/s|J/kg|kJ/kg)",
    re.IGNORECASE,
)
_CONCENTRATION_PAT = re.compile(
    r"(?:质量分数|体积分数|浓度)\s*\d+(?:\.\d+)?\s*%|"
    r"\d+(?:\.\d+)?\s*(?:wt\s*%|vol\s*%|%)\s*(?:EGW|PGW|ethylene\s+glycol\s+water|propylene\s+glycol\s+water)?",
    re.IGNORECASE,
)
_FLOW_UNIT_PAT = re.compile(r"\b(?:L/min|LPM|kg/s)\b", re.IGNORECASE)
_SYMBOL_PAT = re.compile(r"\b(?:Nu|Re|Pr|Bi|Fo|Gr|Ra|St|Q|m_dot|cp|Rth)\b|ΔT|Rθ", re.IGNORECASE)
_PROPERTY_LOOKUP_PAT = re.compile(
    r"比热容|比热|密度|黏度|粘度|导热系数|热导率|物性|物性参数|"
    r"specific\s+heat|\bcp\b|\bc_p\b|density|viscosity|thermal\s+conductivity|property",
    re.IGNORECASE,
)
_COOLANT_PROPERTY_CONTEXT_PAT = re.compile(
    r"冷却液|冷媒|工质|乙二醇|丙二醇|glycol|\bEGW\b|\bPGW\b|coolant|water\s+glycol|"
    r"ethylene\s+glycol\s+water|propylene\s+glycol\s+water|冷却水|cooling\s+water|"
    r"(?<!乙二醇)(?<!丙二醇)(?:水的|水在|\bwater\b)",
    re.IGNORECASE,
)
_TEMPERATURE_PAT = re.compile(r"\d+(?:\.\d+)?\s*(?:℃|°c|degc|\bc\b|\bk\b)", re.IGNORECASE)
_FORMULA_EXPRESSION_PAT = re.compile(r"(?:=|ΔT|\bm_dot\b|\bR_total\b|\bR_required\b|\bTj\b|\bTin\b)", re.IGNORECASE)

_THERMAL_ANALOGY_PAT = re.compile(
    r"冷板|液冷|冷却液|CDU|TIM|热阻|流道|泵|换热器|芯片|服务器|"
    r"cold\s+plate|liquid\s+cooling|coolant|thermal\s+resistance|flow\s+channel|pump|heat\s+exchanger",
    re.IGNORECASE,
)
_NON_ENGINEERING_ANALOGY_PAT = re.compile(r"食堂|排队|奶茶|公交|宿舍|游戏|电影院|超市|楼道|交通", re.IGNORECASE)

_PROPERTY_LOOKUP_EXPANSIONS = [
    "物性参数",
    "比热容",
    "specific heat",
    "cp",
    "density",
    "viscosity",
    "thermal conductivity",
    "乙二醇水溶液",
    "ethylene glycol water",
    "propylene glycol water",
    "EGW",
    "PGW",
    "property table",
    "datasheet",
    "engineering handbook",
    "temperature",
    "concentration",
]

_DOMAIN_EXPANSIONS: dict[str, list[str]] = {
    "遮热板": ["辐射换热", "热辐射", "辐射传热"],
    "牛顿冷却": ["牛顿冷却定律", "对流换热", "适用条件"],
    "傅里叶定律": ["导热", "热流密度", "温度梯度"],
    "导热系数": ["热导率"],
    "热导率": ["导热系数"],
    "对流系数": ["换热系数", "对流换热系数"],
    "换热系数": ["对流换热系数"],
    "密度": ["物性参数", "热物性"],
    "焓": ["热力性质", "比焓"],
    "边界层": ["速度边界层", "热边界层"],
    "黑体": ["辐射率", "热辐射"],
    "努塞尔数": ["Nu", "无量纲换热"],
    "普朗特数": ["Pr", "无量纲参数"],
    "雷诺数": ["Re", "无量纲参数"],
    "毕渥数": ["Bi", "无量纲参数"],
    "傅里叶数": ["Fo", "无量纲参数"],
    "二氧化碳": ["CO2", "热物性"],
    "co2": ["二氧化碳", "热物性"],
}


def _dedupe_keep_order(items: list[str], *, max_items: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = (item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if max_items is not None and len(out) >= max_items:
            break
    return out


def _normalize_query(question: str) -> str:
    q = re.sub(r"\s+", " ", (question or "").strip())
    return q.replace("？", "?").replace("，", ",").replace("：", ":").strip()


def _normalize_reference_token(token: str) -> str:
    s = (token or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("－", "-").replace("–", "-").replace("—", "-").replace(".", "-")
    s = re.sub(r"\s+", "", s)
    return s


def _extract_preserved_tokens(question: str) -> list[str]:
    refs = _REF_PAT.findall(question)
    concentrations = _CONCENTRATION_PAT.findall(question)
    nums = _NUMUNIT_PAT.findall(question)
    flow_units = _FLOW_UNIT_PAT.findall(question)
    syms = [m.group(0) for m in _SYMBOL_PAT.finditer(question)]
    normalized_refs = [_normalize_reference_token(x) for x in refs]
    return _dedupe_keep_order([*normalized_refs, *concentrations, *nums, *flow_units, *syms], max_items=20)


def _is_property_lookup_question(question: str) -> bool:
    if not question:
        return False
    has_property = bool(_PROPERTY_LOOKUP_PAT.search(question))
    has_context = bool(_COOLANT_PROPERTY_CONTEXT_PAT.search(question))
    has_concentration = bool(_CONCENTRATION_PAT.search(question))
    return has_property and (has_context or has_concentration)


def _is_irrelevant_or_analogy_question(question: str) -> bool:
    return bool(_THERMAL_ANALOGY_PAT.search(question or "")) and bool(_NON_ENGINEERING_ANALOGY_PAT.search(question or ""))


def _infer_intent(question: str) -> str:
    if re.search(r"(图\s*\d|图\d|图示|示意图)", question):
        return "figure_lookup"
    if _is_irrelevant_or_analogy_question(question):
        return "irrelevant_or_analogy"
    if _is_property_lookup_question(question):
        return "property_lookup"
    if re.search(r"(表\s*\d|表\d|查表|参数表|物性表)", question):
        return "table_lookup"
    if re.search(r"(焓|熵|压缩因子)", question):
        return "property_lookup"
    if re.search(r"(适用条件|使用条件|何时适用|什么时候能用|什么时候不能用|为什么不能)", question):
        return "applicability"
    if re.search(r"(物理意义|意义是什么)", question):
        return "physical_meaning"
    if re.search(r"(公式|定律|表达式|推导|变量|怎么算|计算式)", question) or _FORMULA_EXPRESSION_PAT.search(question or ""):
        return "formula"
    if re.search(r"(区别|比较|不同|联系|各自|分别)", question):
        return "comparison"
    if re.search(r"(例题|习题|解题|步骤|怎么做|求解|一般怎么分析)", question):
        return "example"
    if re.search(r"(为什么|原因|机理|作用)", question):
        return "mechanism"
    return "concept"


def _prefer_chunk_types(intent: str) -> list[str]:
    if intent in {"table_lookup", "property_lookup"}:
        return ["table", "table_summary", "text"]
    if intent == "figure_lookup":
        return ["figure", "text"]
    if intent in {"formula", "applicability", "physical_meaning"}:
        return ["text", "table"]
    return ["text", "table"]


def _expand_terms(question: str) -> list[str]:
    lowered = question.lower()
    terms: list[str] = []
    if _is_property_lookup_question(question):
        terms.extend(_PROPERTY_LOOKUP_EXPANSIONS)
    for key, vals in _DOMAIN_EXPANSIONS.items():
        if key.lower() in lowered:
            terms.extend(vals)
    return _dedupe_keep_order(terms, max_items=18)


def _make_rewritten_queries(question: str, *, intent: str, preserved: list[str], max_items: int) -> list[str]:
    refs = " ".join(preserved[:2]).strip()
    queries: list[str] = []
    if intent == "figure_lookup":
        queries.append(f"{question} 图注 解释 所在章节".strip())
    elif intent == "irrelevant_or_analogy":
        queries.append(f"{question} 教学类比 工程边界 没有直接工程关系 不能用于工程设计".strip())
    elif intent == "table_lookup":
        queries.append(f"{question} 相关表格 物性参数 条件".strip())
    elif intent == "property_lookup":
        expansions = " ".join(_PROPERTY_LOOKUP_EXPANSIONS)
        queries.append(f"{question} {expansions}".strip())
    elif intent == "formula":
        queries.append(f"{question} 公式 表达式 变量含义".strip())
    elif intent == "applicability":
        queries.append(f"{question} 适用条件 使用范围 假设前提".strip())
    elif intent == "physical_meaning":
        queries.append(f"{question} 定义 物理意义 解释".strip())
    elif intent == "comparison":
        queries.append(f"{question} 定义 区别 联系 适用范围".strip())
    elif intent == "example":
        queries.append(f"{question} 解题思路 步骤 使用公式".strip())
    elif intent == "mechanism":
        queries.append(f"{question} 物理意义 作用 机理".strip())
    else:
        queries.append(f"{question} 定义 物理意义 作用".strip())
    if refs and intent not in {"figure_lookup", "table_lookup"}:
        queries.append(f"{question} {refs}".strip())
    return _dedupe_keep_order(queries, max_items=max_items)


def _make_keyword_queries(question: str, *, preserved: list[str], max_items: int) -> list[str]:
    terms = _expand_terms(question)
    compact_refs = [_normalize_reference_token(t) for t in preserved if t]
    out: list[str] = []
    line1 = " ".join(_dedupe_keep_order([question, *compact_refs, *terms], max_items=10)).strip()
    if line1:
        out.append(line1)
    if compact_refs:
        line2 = " ".join(_dedupe_keep_order([*compact_refs, *terms], max_items=8)).strip()
        if line2:
            out.append(line2)
    return _dedupe_keep_order(out, max_items=max_items)


def _make_sub_queries(question: str, *, intent: str, max_items: int) -> list[str]:
    out: list[str] = []
    q = question.strip()
    if intent == "irrelevant_or_analogy":
        out.append(f"{q} 教学类比的工程边界是什么")
    elif intent == "comparison":
        m = re.search(r"(.+?)和(.+?)(有什么区别|区别是什么|有何不同|不同点是什么)", q)
        if m:
            left = m.group(1).strip(" ，,。?")
            right = m.group(2).strip(" ，,。?")
            out.extend([
                f"{left} 的定义和适用条件是什么",
                f"{right} 的定义和适用条件是什么",
            ])
    elif intent == "applicability":
        out.append(f"{q} 对应公式或定律的适用条件是什么")
    elif intent == "property_lookup":
        out.append(f"{q} 流体类型 浓度 温度 物性名 数值 单位 物性表 datasheet")
    return _dedupe_keep_order(out, max_items=max_items)


def _rule_based_query_plan(cfg: AppConfig, question: str) -> QueryPlan:
    q = _normalize_query(question)
    if not q:
        return QueryPlan(original_query="", intent="general")
    intent = _infer_intent(q)
    preserved = _extract_preserved_tokens(q)
    rewritten = _make_rewritten_queries(q, intent=intent, preserved=preserved, max_items=cfg.retrieval.max_rewrite_queries) if cfg.retrieval.query_rewrite_enable else []
    keywords = _make_keyword_queries(q, preserved=preserved, max_items=cfg.retrieval.max_keyword_queries) if cfg.retrieval.keyword_expansion_enable else []
    sub_queries = _make_sub_queries(q, intent=intent, max_items=cfg.retrieval.max_sub_queries) if cfg.retrieval.subquery_enable else []
    notes: list[str] = []
    if preserved:
        notes.append("preserved_reference_tokens")
    if any(t.startswith(("图", "表", "式")) for t in preserved):
        notes.append("exact_reference_route")
    if intent in {"figure_lookup", "table_lookup", "property_lookup"}:
        notes.append("prefer_structured_chunks")
    if intent == "irrelevant_or_analogy":
        notes.append("avoid_concept_template_expansion")
    return QueryPlan(
        original_query=q,
        rewritten_queries=rewritten,
        keyword_queries=keywords,
        sub_queries=sub_queries,
        intent=intent,
        prefer_chunk_types=_prefer_chunk_types(intent),
        preserved_tokens=preserved,
        notes=notes,
    )


def analyze_query(cfg: AppConfig, question: str, *, planner: Callable[[str], QueryPlan] | None = None) -> QueryPlan:
    if planner is not None:
        plan = planner(question)
        if not isinstance(plan, QueryPlan):
            raise TypeError("custom planner must return QueryPlan")
        return plan
    if not cfg.retrieval.pre_retrieval_enable:
        q = _normalize_query(question)
        intent = _infer_intent(q)
        return QueryPlan(original_query=q, intent=intent, prefer_chunk_types=_prefer_chunk_types(intent))
    return _rule_based_query_plan(cfg, question)
