from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .domain_rules import ashrae_rules, rule_registry
from .domain_rules.thermal_terms import dedupe as _dedupe
from .domain_rules.thermal_terms import expand_terms, keywords_from_query, task_keywords
from .task_understanding import TaskUnderstandingResult, extract_entities, normalize_query


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

_ANALOGY_EXPANSIONS = [
    "教学类比",
    "工程边界",
    "没有直接工程关系",
    "不能用于工程设计",
    "不能用于可靠性判断",
]


@dataclass(frozen=True)
class QueryRewriteResult:
    """Query rewriting output consumed by retrieval and API responses."""

    original_query: str
    rewritten_query: str
    expanded_queries: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _task_type(task_result: TaskUnderstandingResult | Mapping[str, Any]) -> str:
    if isinstance(task_result, TaskUnderstandingResult):
        return task_result.task_type
    return str(task_result.get("task_type") or "general_qa")


def _entities(query: str, task_result: TaskUnderstandingResult | Mapping[str, Any] | None) -> list[str]:
    if isinstance(task_result, TaskUnderstandingResult):
        values = task_result.entities
    elif isinstance(task_result, Mapping):
        raw = task_result.get("entities") or []
        values = [str(x) for x in raw if x]
    else:
        values = []
    return _dedupe([*values, *extract_entities(query)])


# Compatibility wrappers for older imports/tests.
def _is_ashrae_query(query: str, entities: list[str]) -> bool:
    return ashrae_rules.is_ashrae_query(query, entities)


def _append_ashrae_range_entities(query: str, entities: list[str]) -> list[str]:
    return ashrae_rules.append_entities(query, entities)


def _ashrae_expanded_queries(query: str, entities: list[str]) -> list[str]:
    return ashrae_rules.ashrae_expanded_queries(query, entities)


def rewrite_query(query: str, task_result: TaskUnderstandingResult | Mapping[str, Any] | None = None) -> QueryRewriteResult:
    """Generate retrieval-oriented query variants with domain rules isolated."""

    original = query or ""
    normalized = normalize_query(original)
    task = _task_type(task_result or {})
    entities = rule_registry.apply_entity_rules(normalized, _entities(normalized, task_result))
    is_domain_specific = rule_registry.is_domain_specific_query(normalized, entities)

    term_expansions = expand_terms(entities, normalized)
    task_terms = [] if is_domain_specific else task_keywords(task)
    special_terms: list[str] = []
    if task == "property_lookup":
        special_terms = _PROPERTY_LOOKUP_EXPANSIONS
    elif task in {"irrelevant_or_analogy", "analogy_query"}:
        special_terms = _ANALOGY_EXPANSIONS
    keywords = _dedupe([*entities, *keywords_from_query(normalized), *task_terms, *term_expansions, *special_terms], max_items=40)

    if task == "property_lookup":
        rewritten = " ".join(_dedupe([normalized, *entities[:5], *_PROPERTY_LOOKUP_EXPANSIONS[:10]], max_items=18)).strip()
        expanded = _dedupe(
            [
                rewritten,
                "物性参数 比热容 specific heat cp density viscosity thermal conductivity",
                "乙二醇水溶液 ethylene glycol water propylene glycol water EGW PGW",
                "property table datasheet engineering handbook temperature concentration",
            ],
            max_items=8,
        )
    elif task in {"irrelevant_or_analogy", "analogy_query"}:
        rewritten = " ".join(_dedupe([normalized, *entities[:5], *_ANALOGY_EXPANSIONS], max_items=14)).strip()
        expanded = _dedupe(
            [
                rewritten,
                "教学类比 工程边界 没有直接工程关系",
                "不能用于工程设计 计算 可靠性判断",
            ],
            max_items=6,
        )
    elif is_domain_specific:
        expanded = rule_registry.expanded_queries(normalized, entities)
        if (
            "ASHRAE" in entities
            and ("供水" in normalized or "water supply" in normalized.lower() or "facility water supply" in normalized.lower())
            and ("推荐" in normalized or "允许" in normalized or "recommended" in normalized.lower() or "allowable" in normalized.lower())
        ):
            expanded.extend(
                [
                    "ASHRAE recommended allowable facility water supply temperature range",
                    "recommended allowable facility water supply temperature",
                ]
            )
        expanded = _dedupe(expanded, max_items=8)
        rewritten = expanded[0] if expanded else normalized
    else:
        core_parts = [normalized, *entities[:5], *task_terms[:4]]
        rewritten = " ".join(_dedupe(core_parts, max_items=12)).strip() or normalized
        expanded = [rewritten]
        if entities or task_terms:
            expanded.append(" ".join(_dedupe([*entities, *task_terms, "散热", "热管理"], max_items=12)))
        if term_expansions:
            expanded.append(" ".join(_dedupe(term_expansions, max_items=12)))
        if "液冷" in entities and any(term in entities for term in ("GPU", "服务器", "AI服务器", "数据中心")):
            expanded.append("GPU liquid cooling high power server thermal management")
            expanded.append("液冷 冷板 CDU 冷却液 热阻 PUE")
        if "风冷" in entities and "液冷" in entities:
            expanded.append("风冷 液冷 对比 数据中心 高功率服务器")
            expanded.append("air cooling vs liquid cooling server thermal design")
        if task == "troubleshooting":
            expanded.append("温度异常 过热 降频 散热 排查 热路径 TIM 风扇 泵")
        elif task == "design_advice":
            expanded.append("热设计 方案选型 热负载 空间约束 可靠性 运维风险")
        elif task == "literature_lookup":
            expanded.append("资料 来源 章节 页码 文献依据")
        expanded = _dedupe(expanded, max_items=8)

    return QueryRewriteResult(
        original_query=original,
        rewritten_query=rewritten,
        expanded_queries=expanded,
        keywords=keywords,
        entities=entities,
    )
