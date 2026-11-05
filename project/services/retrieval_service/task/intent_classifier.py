from __future__ import annotations

import re

from ..domain_rules import ashrae_rules
from .calculation_intent import is_lookup_range_query
from .normalizer import normalize_query
from .property_lookup import is_irrelevant_or_analogy_query, is_property_lookup_query


_TASK_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "report",
        (
            "分析报告",
            "生成报告",
            "报告",
            "markdown report",
            "engineering report",
        ),
    ),
    (
        "simulation",
        (
            "仿真准备",
            "仿真准备检查",
            "simulation readiness",
            "simulation preparation",
            "cabinet_model.step",
            ".step",
            ".stp",
        ),
    ),
    (
        "visualization",
        (
            "画图",
            "图结构",
            "散热路径图",
            "热阻网络",
            "液冷回路",
            "可视化",
            "diagram",
            "graph",
            "visualization",
        ),
    ),
    (
        "literature_lookup",
        (
            "来源",
            "出处",
            "文献",
            "资料",
            "引用",
            "依据",
            "哪本书",
            "哪一章",
            "章节",
            "页码",
            "table",
            "source",
            "reference",
            "literature",
        ),
    ),
    (
        "troubleshooting",
        (
            "故障",
            "异常",
            "过热",
            "温度高",
            "降频",
            "报警",
            "失效",
            "不稳定",
            "排查",
            "troubleshoot",
            "failure",
            "overheat",
        ),
    ),
    (
        "comparison",
        (
            "对比",
            "比较",
            "区别",
            "差异",
            "不同",
            "优缺点",
            "哪个好",
            "相比",
            "versus",
            "vs",
            "compare",
            "comparison",
        ),
    ),
    (
        "design_advice",
        (
            "设计",
            "方案",
            "选型",
            "建议",
            "优化",
            "改进",
            "适合",
            "如何选择",
            "怎么选",
            "可行吗",
            "design",
            "recommend",
            "optimize",
        ),
    ),
    (
        "mechanism_analysis",
        (
            "机理",
            "原理",
            "为什么",
            "为何",
            "原因",
            "影响因素",
            "作用机制",
            "怎么实现",
            "mechanism",
            "why",
        ),
    ),
    (
        "concept_explanation",
        (
            "是什么",
            "什么是",
            "解释",
            "定义",
            "概念",
            "含义",
            "作用",
            "介绍",
            "范围是多少",
            "是多少",
            "what is",
            "explain",
            "definition",
        ),
    ),
]

_VISUAL_HINTS = ("画", "图", "示意图", "流程图", "可视化", "diagram", "chart", "plot")


def has_visualization_hint(query: str) -> bool:
    normalized = normalize_query(query)
    return any(hint.lower() in normalized.lower() for hint in _VISUAL_HINTS)


def _score_task_type(query: str, task_type: str, keywords: tuple[str, ...]) -> int:
    lowered = query.lower()
    score = sum(1 for keyword in keywords if keyword.lower() in lowered)
    if task_type == "comparison" and re.search(r"(.+)(和|与|跟|同)(.+)(区别|差异|比较|对比)", query):
        score += 2
    if task_type == "literature_lookup" and ashrae_rules.is_ashrae_query(query):
        score += 1
    if task_type == "troubleshooting" and re.search(r"(温度|散热|冷却).*(高|异常|报警|不稳|失效)", query):
        score += 2
    return score


def classify_task_type(query: str) -> tuple[str, float]:
    """Classify query into the stable task taxonomy required by the API."""

    normalized = normalize_query(query)
    if not normalized:
        return "general_qa", 0.2
    if is_irrelevant_or_analogy_query(normalized):
        return "irrelevant_or_analogy", 0.9
    if is_property_lookup_query(normalized):
        return "property_lookup", 0.88
    if is_lookup_range_query(normalized):
        if ashrae_rules.is_ashrae_query(normalized):
            return "literature_lookup", 0.78
        return "general_qa", 0.68

    scored = [(task_type, _score_task_type(normalized, task_type, keywords)) for task_type, keywords in _TASK_RULES]
    best_type, best_score = max(scored, key=lambda item: item[1])
    if best_score <= 0:
        return "general_qa", 0.45
    return best_type, min(0.95, 0.58 + best_score * 0.08)


def build_intent(query: str, task_type: str, entities: list[str]) -> str:
    """Create a compact human-readable intent string."""

    normalized = normalize_query(query)
    entity_text = "、".join(entities[:6])
    if task_type == "property_lookup":
        return f"查找{entity_text or normalized}在指定温度、浓度和物性名下的可靠物性表数值"
    if task_type == "irrelevant_or_analogy":
        return f"判断{entity_text or normalized}与日常对象之间是否只是教学类比，并说明工程边界"
    if task_type == "concept_explanation":
        return f"解释{entity_text or normalized}的概念、范围或作用"
    if task_type == "mechanism_analysis":
        return f"分析{entity_text or normalized}背后的热管理机理"
    if task_type == "comparison":
        return f"对比{entity_text or normalized}的差异、优势和适用场景"
    if task_type == "troubleshooting":
        return f"分析{entity_text or normalized}相关异常的可能原因和排查路径"
    if task_type == "design_advice":
        return f"围绕{entity_text or normalized}给出热管理设计建议"
    if task_type == "literature_lookup":
        return f"查找{entity_text or normalized}相关标准、表格、章节或来源"
    if task_type == "visualization":
        return f"识别{entity_text or normalized}所需的工程图结构或散热路径表达"
    if task_type == "report":
        return f"整理{entity_text or normalized}的规则式工程分析报告需求"
    if task_type == "simulation":
        return f"检查{entity_text or normalized}的仿真准备条件，不执行 CFD 求解"
    return normalized or "普通问答"
