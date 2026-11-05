from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .critique_types import CritiqueIssue, CritiqueResult, issue


PROPERTY_TERMS = (
    "比热容",
    "比热",
    "cp",
    "c_p",
    "specific heat",
    "密度",
    "density",
    "黏度",
    "粘度",
    "viscosity",
    "导热系数",
    "热导率",
    "thermal conductivity",
    "物性",
    "物性参数",
)

GLYCOL_TERMS = (
    "乙二醇",
    "丙二醇",
    "EGW",
    "PGW",
    "glycol",
    "ethylene glycol",
    "propylene glycol",
)

THERMAL_ANALOGY_TERMS = (
    "冷板",
    "液冷",
    "冷却液",
    "CDU",
    "TIM",
    "热阻",
    "流道",
    "机柜",
    "服务器",
)

DAILY_ANALOGY_TERMS = (
    "食堂",
    "排队",
    "奶茶",
    "公交",
    "地铁",
    "游戏",
    "宿舍",
    "电影院",
    "超市",
)

_PROPERTY_NUMERIC_RE = re.compile(
    r"(?:cp|c_p|比热容|比热|specific\s+heat|密度|density|黏度|粘度|viscosity|导热系数|热导率|thermal\s+conductivity)"
    r"[^。\n]{0,24}(?:=|为|是|约为|:|：)?\s*\d+(?:\.\d+)?",
    re.IGNORECASE,
)

_PROPERTY_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:"
    r"J\s*/?\s*\(?\s*kg\s*[·*]?\s*K\s*\)?|J/kgK|"
    r"kg\s*/?\s*m(?:3|³)|"
    r"Pa\s*[·*]?\s*s|mPa\s*[·*]?\s*s|"
    r"W\s*/?\s*\(?\s*m\s*[·*]?\s*K\s*\)?"
    r")",
    re.IGNORECASE,
)

_CONCENTRATION_RE = re.compile(r"\d+(?:\.\d+)?\s*%|质量分数|体积分数|浓度", re.IGNORECASE)
_TEMPERATURE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:℃|°C|degC|\bC\b|\bK\b)", re.IGNORECASE)

_SAFE_PROPERTY_PHRASES = (
    "当前知识库未检索到",
    "未检索到该物性参数的直接数值",
    "不能给出确定",
    "不能给出该物性",
    "不能确定",
    "没有可靠数值",
    "可靠数值，因此不返回数值",
    "不返回数值",
    "本地正式物性层没有",
    "需要物性表",
    "厂商数据",
    "工程手册",
)

_CALCULATION_KEYS = {
    "volume_flow_L_min": ("L/min", re.compile(r"(\d+(?:\.\d+)?)\s*(?:L\s*/\s*min|L/min|lpm)\b", re.IGNORECASE)),
    "mass_flow_kg_s": ("kg/s", re.compile(r"(\d+(?:\.\d+)?)\s*kg\s*/\s*s\b", re.IGNORECASE)),
    "heat_rate_W": ("W", re.compile(r"(\d+(?:\.\d+)?)\s*W\b", re.IGNORECASE)),
    "T_j_C": ("degC", re.compile(r"(\d+(?:\.\d+)?)\s*(?:degC\b|℃|°C)", re.IGNORECASE)),
    "R_required_K_per_W": ("K/W", re.compile(r"(\d+(?:\.\d+)?)\s*(?:K\s*/\s*W|K/W|℃\s*/\s*W)\b", re.IGNORECASE)),
    "R_cond_K_per_W": ("K/W", re.compile(r"(\d+(?:\.\d+)?)\s*(?:K\s*/\s*W|K/W|℃\s*/\s*W)\b", re.IGNORECASE)),
    "delta_T_K": ("K", re.compile(r"(?:温升|温差|ΔT|delta\s*T|dT)[^。\n]{0,16}(\d+(?:\.\d+)?)\s*(?:K|℃|°C)\b", re.IGNORECASE)),
}

_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("replace_cfd", re.compile(r"(?:本系统)?(?:可以|可|能够)\s*替代\s*CFD", re.IGNORECASE), "声称可替代 CFD。"),
    ("no_cfd_needed", re.compile(r"不需要\s*CFD", re.IGNORECASE), "声称不需要 CFD。"),
    ("direct_engineering", re.compile(r"可以直接用于工程实施", re.IGNORECASE), "声称可直接用于工程实施。"),
    ("simulation_done", re.compile(r"已完成仿真", re.IGNORECASE), "声称已完成仿真。"),
    ("cfd_result", re.compile(r"CFD\s*结果表明", re.IGNORECASE), "声称存在 CFD 结果。"),
    ("temperature_field", re.compile(r"温度场结果为", re.IGNORECASE), "声称存在温度场结果。"),
    ("velocity_field", re.compile(r"速度场结果为", re.IGNORECASE), "声称存在速度场结果。"),
    ("pressure_drop_numeric", re.compile(r"压降\s*为\s*\d+(?:\.\d+)?\s*kPa", re.IGNORECASE), "给出未验证压降数值。"),
    ("pump_curve", re.compile(r"泵曲线\s*为", re.IGNORECASE), "声称存在泵曲线。"),
    ("vendor_data", re.compile(r"厂家性能数据表明", re.IGNORECASE), "声称存在厂家性能数据。"),
    ("industrial_design_done", re.compile(r"工业级冷板设计已完成", re.IGNORECASE), "声称工业级冷板设计已完成。"),
    ("generic_graph_overclaim", re.compile(r"(?:仿真模型自动生成|真实机柜流场|真实流场|反映真实(?:机柜)?流场)", re.IGNORECASE), "将示意图或通用图结构表述为真实仿真/流场结果。"),
)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    return {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _has_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _metadata_get(metadata: Mapping[str, Any], *keys: str) -> Any:
    value: Any = metadata
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _is_property_lookup_query(query: str, metadata: Mapping[str, Any]) -> bool:
    template = str(_metadata_get(metadata, "knowledge", "template_type") or "")
    retrieval_intent = str(_metadata_get(metadata, "retrieval_plan", "intent") or "")
    text = query or ""
    if template == "property_lookup" or retrieval_intent == "property_lookup":
        return True
    has_property = _has_any(text, PROPERTY_TERMS)
    has_context = _has_any(text, GLYCOL_TERMS) or "冷却液" in text or "coolant" in text.lower() or bool(_CONCENTRATION_RE.search(text))
    return has_property and has_context


def _answer_is_conservative_property(answer: str) -> bool:
    text = answer or ""
    conservative_outcome = (
        "不能给出确定" in text
        or "不能确定" in text
        or "不返回数值" in text
        or ("没有" in text and "可靠数值" in text)
    )
    conservative_basis = (
        "未检索到" in text
        or "本地正式物性层" in text
        or "需要物性表" in text
        or "厂商数据" in text
        or "工程手册" in text
    )
    return conservative_outcome and conservative_basis


def _answer_has_property_numeric_claim(answer: str) -> bool:
    text = answer or ""
    if _PROPERTY_NUMERIC_RE.search(text):
        return True
    return bool(_PROPERTY_UNIT_RE.search(text) and _has_any(text, PROPERTY_TERMS))


def _source_text(sources: Sequence[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for source in sources or []:
        if not isinstance(source, Mapping):
            continue
        for key in ("title", "book_title", "chapter", "section", "section_path", "text_preview", "text", "preview"):
            value = source.get(key)
            if value:
                parts.append(str(value))
    return " ".join(parts)


def _sources_cover_property_claim(query: str, sources: Sequence[dict[str, Any]] | None) -> bool:
    if not sources:
        return False
    query_text = query or ""
    text = _source_text(sources)
    if not text:
        return False
    has_property = _has_any(text, [term for term in PROPERTY_TERMS if term.lower() in query_text.lower()]) or _has_any(text, PROPERTY_TERMS)
    has_fluid = _has_any(text, GLYCOL_TERMS) if _has_any(query_text, GLYCOL_TERMS) else _has_any(text, ("冷却液", "coolant", "water", "水"))
    needs_concentration = bool(_CONCENTRATION_RE.search(query_text)) or _has_any(query_text, GLYCOL_TERMS)
    has_concentration = (not needs_concentration) or bool(_CONCENTRATION_RE.search(text))
    has_temperature = bool(_TEMPERATURE_RE.search(text))
    has_numeric_unit = bool(_PROPERTY_UNIT_RE.search(text))
    return has_property and has_fluid and has_concentration and has_temperature and has_numeric_unit


def _check_source_sufficiency(query: str, answer: str, sources: list[dict] | None, metadata: Mapping[str, Any]) -> list[CritiqueIssue]:
    calculation = _as_mapping(metadata.get("calculation"))
    if bool(calculation.get("used_calculation")) and str(calculation.get("tool_status") or "").lower() in {"ok", "success"}:
        return []
    if not _is_property_lookup_query(query, metadata):
        return []
    if _answer_is_conservative_property(answer):
        return []
    if not _answer_has_property_numeric_claim(answer):
        return []
    if _sources_cover_property_claim(query, sources):
        return []
    return [
        issue(
            type="source_insufficient",
            severity="warning",
            message="物性查表回答给出了确定数值，但 sources 未充分覆盖流体类型、浓度、温度、物性名、明确数值和单位。",
            suggested_action="replace_with_property_lookup_insufficient_source_template",
            evidence={"sources_count": len(sources or []), "query": query},
            node="source_sufficiency_checker",
        )
    ]


def _is_analogy_query(query: str, metadata: Mapping[str, Any]) -> bool:
    template = str(_metadata_get(metadata, "knowledge", "template_type") or "")
    if template == "irrelevant_or_analogy":
        return True
    text = query or ""
    return _has_any(text, THERMAL_ANALOGY_TERMS) and _has_any(text, DAILY_ANALOGY_TERMS)


def _check_analogy_boundary(query: str, answer: str, metadata: Mapping[str, Any]) -> list[CritiqueIssue]:
    if not _is_analogy_query(query, metadata):
        return []
    text = answer or ""
    has_no_direct = "没有直接工程关系" in text or "没有直接关系" in text or "无直接工程关系" in text
    has_teaching = "教学类比" in text or "类比" in text
    has_no_design = any(
        phrase in text
        for phrase in (
            "不能作为工程设计",
            "不能用于工程设计",
            "不能作为冷板设计",
            "不能作为液冷设计",
            "不能作为工程计算",
            "不能作为可靠性判断",
        )
    )
    if has_no_direct and has_teaching and has_no_design:
        return []
    return [
        issue(
            type="analogy_boundary_missing",
            severity="warning",
            message="跨域类比回答缺少直接关系、教学类比或工程设计/计算/可靠性边界说明。",
            suggested_action="replace_with_analogy_boundary_template",
            evidence={"query": query},
            node="source_sufficiency_checker",
        )
    ]


def _calculation_result(metadata: Mapping[str, Any]) -> dict[str, Any]:
    calculation = _as_mapping(metadata.get("calculation"))
    result = _as_mapping(calculation.get("tool_result"))
    if result:
        return result
    return _as_mapping(metadata.get("tool_result"))


def _check_calculation_consistency(answer: str, metadata: Mapping[str, Any]) -> list[CritiqueIssue]:
    calculation = _as_mapping(metadata.get("calculation"))
    if not bool(calculation.get("used_calculation")):
        return []
    result = _calculation_result(metadata)
    issues: list[CritiqueIssue] = []
    for key, (unit, pattern) in _CALCULATION_KEYS.items():
        expected_raw = result.get(key)
        if expected_raw is None:
            continue
        try:
            expected = float(expected_raw)
        except (TypeError, ValueError):
            continue
        matches = [float(match.group(1)) for match in pattern.finditer(answer or "")]
        if not matches:
            continue
        nearest = min(matches, key=lambda value: abs(value - expected))
        tolerance = max(abs(expected) * 0.15, 0.2)
        if abs(nearest - expected) > tolerance:
            issues.append(
                issue(
                    type="calculation_mismatch",
                    severity="warning",
                    message=f"回答中的 {unit} 数值与 metadata.calculation.tool_result.{key} 明显不一致。",
                    suggested_action="review_calculation_answer",
                    evidence={"key": key, "tool_result": expected, "answer_value": nearest, "unit": unit},
                    node="calculation_consistency_checker",
                )
            )
            break
    return issues


def _is_agent_metadata(metadata: Mapping[str, Any]) -> bool:
    agent_keys = {
        "analysis_mode",
        "analysis_workflow",
        "visualization",
        "simulation",
        "solution",
        "comparison",
        "report",
        "retrieval_count",
        "used_calculation",
        "tool_name",
        "tool_status",
    }
    return bool(agent_keys.intersection(metadata.keys()))


def _check_metadata_consistency(query: str, metadata: Mapping[str, Any]) -> list[CritiqueIssue]:
    issues: list[CritiqueIssue] = []
    if _is_agent_metadata(metadata) and "calculation" not in metadata:
        issues.append(
            issue(
                type="metadata_mismatch",
                severity="warning",
                message="agent metadata 缺少 metadata.calculation。",
                suggested_action="review_metadata_contract",
                evidence={"missing": "calculation"},
                node="metadata_consistency_checker",
            )
        )

    analysis_workflow = _as_mapping(metadata.get("analysis_workflow"))
    analysis_mode = _as_mapping(metadata.get("analysis_mode"))
    if analysis_workflow.get("enabled") is True and analysis_mode.get("enabled") is False:
        issues.append(
            issue(
                type="metadata_mismatch",
                severity="warning",
                message="metadata.analysis_workflow.enabled=true 但 metadata.analysis_mode.enabled=false。",
                suggested_action="review_metadata_contract",
                evidence={"analysis_workflow": analysis_workflow, "analysis_mode": analysis_mode},
                node="metadata_consistency_checker",
            )
        )

    simulation = _as_mapping(metadata.get("simulation"))
    readiness = _as_mapping(simulation.get("readiness"))
    missing_conditions = _as_list(readiness.get("missing_conditions")) or _as_list(simulation.get("missing_conditions"))
    if simulation.get("simulation_ready") is True and missing_conditions:
        issues.append(
            issue(
                type="metadata_mismatch",
                severity="warning",
                message="metadata.simulation.simulation_ready=true 但 missing_conditions 非空。",
                suggested_action="review_metadata_contract",
                evidence={"missing_conditions": missing_conditions},
                node="metadata_consistency_checker",
            )
        )

    visualization = _as_mapping(metadata.get("visualization"))
    graph = _as_mapping(visualization.get("graph"))
    if visualization.get("generated") is True and (not graph.get("nodes") or not graph.get("edges")):
        issues.append(
            issue(
                type="metadata_mismatch",
                severity="warning",
                message="metadata.visualization.generated=true 但 graph 缺少 nodes 或 edges。",
                suggested_action="review_metadata_contract",
                evidence={"graph_keys": sorted(graph.keys())},
                node="metadata_consistency_checker",
            )
        )

    report = _as_mapping(metadata.get("report"))
    if report.get("generated") is True and not str(report.get("content") or "").strip():
        issues.append(
            issue(
                type="metadata_mismatch",
                severity="warning",
                message="metadata.report.generated=true 但 content 为空。",
                suggested_action="review_metadata_contract",
                evidence={"report": {"generated": report.get("generated"), "format": report.get("format")}},
                node="metadata_consistency_checker",
            )
        )

    template = str(_metadata_get(metadata, "knowledge", "template_type") or "")
    retrieval_intent = str(_metadata_get(metadata, "retrieval_plan", "intent") or "")
    if template == "property_lookup" and retrieval_intent == "concept" and _is_property_lookup_query(query, metadata):
        issues.append(
            issue(
                type="metadata_mismatch",
                severity="warning",
                message="metadata.knowledge.template_type=property_lookup，但 metadata.retrieval_plan.intent=concept。",
                suggested_action="review_metadata_contract",
                evidence={"template_type": template, "retrieval_intent": retrieval_intent},
                node="metadata_consistency_checker",
            )
        )

    return issues


def _metadata_text(metadata: Mapping[str, Any]) -> str:
    parts = [str(_metadata_get(metadata, "report", "content") or "")]
    for key in ("solution", "comparison"):
        value = metadata.get(key)
        if value:
            parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return "\n".join(part for part in parts if part)


def _check_forbidden_claims(answer: str, metadata: Mapping[str, Any]) -> list[CritiqueIssue]:
    text = "\n".join(part for part in (answer or "", _metadata_text(metadata)) if part)
    if not text:
        return []
    issues: list[CritiqueIssue] = []
    for claim_type, pattern, message in _FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        issues.append(
            issue(
                type="forbidden_claim",
                severity="error",
                message=message,
                suggested_action="remove_forbidden_claims",
                evidence={"claim_type": claim_type, "matched_text": match.group(0)},
                node="forbidden_claim_checker",
            )
        )
        break
    return issues


def _aggregate(issues: list[CritiqueIssue]) -> tuple[bool, str, str, str, bool]:
    if not issues:
        return True, "ok", "none", "finalize", False
    severity = "error" if any(item.severity == "error" for item in issues) else "warning"
    if severity == "error":
        route = "human_review"
        requires_human_review = True
    else:
        route = "finalize_with_warning"
        requires_human_review = False

    priority = [
        ("forbidden_claim", "remove_forbidden_claims"),
        ("source_insufficient", "replace_with_property_lookup_insufficient_source_template"),
        ("analogy_boundary_missing", "replace_with_analogy_boundary_template"),
        ("calculation_mismatch", "review_calculation_answer"),
        ("metadata_mismatch", "review_metadata_contract"),
    ]
    issue_types = {item.type for item in issues}
    repair_action = "none"
    for issue_type, action in priority:
        if issue_type in issue_types:
            repair_action = action
            break
    return False, severity, repair_action, route, requires_human_review


def critique_answer(
    query: str,
    answer: str,
    sources: list[dict] | None = None,
    metadata: dict | None = None,
    task: dict | None = None,
    rewrite: dict | None = None,
) -> dict[str, Any]:
    """Critique an answer without mutating the answer or metadata.

    This first-stage critic is an in-process pure logic module. It does not
    access the database, indexes, external APIs, LangGraph, or LLMs.
    """

    meta = _as_mapping(metadata)
    issue_list: list[CritiqueIssue] = []
    issue_list.extend(_check_source_sufficiency(query, answer, sources, meta))
    issue_list.extend(_check_analogy_boundary(query, answer, meta))
    issue_list.extend(_check_calculation_consistency(answer, meta))
    issue_list.extend(_check_metadata_consistency(query, meta))
    issue_list.extend(_check_forbidden_claims(answer, meta))

    passed, severity, repair_action, route, requires_human_review = _aggregate(issue_list)
    return CritiqueResult(
        enabled=True,
        passed=passed,
        severity=severity,
        issues=issue_list,
        repair_action=repair_action,
        route=route,
        requires_human_review=requires_human_review,
    ).to_dict()


__all__ = ["critique_answer"]
