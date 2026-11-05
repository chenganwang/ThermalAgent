from __future__ import annotations

import re
from typing import Any, Mapping

from .repair_policy import get_repair_policy, is_safe_repair_action


BOUNDARY_WARNING = (
    "边界说明：当前回答基于知识库检索、规则模板和一级工程估算，"
    "不替代 CFD、实验测试或工业级冷板设计。"
)

PROPERTY_LOOKUP_INSUFFICIENT_SOURCE_TEMPLATE = (
    "结论：本地正式物性层没有该物性参数的可靠数值；当前知识库未检索到直接数值，不能给出确定结果。\n\n"
    "来源判断：当前 sources 或结构化物性表未同时覆盖流体类型、浓度、温度、物性名、明确数值和单位。\n\n"
    "需要补充：应使用厂商冷却液数据表、乙二醇/丙二醇水溶液物性表或工程手册，并记录 source_status、页码或表格位置。\n\n"
    "边界说明：不能默认使用水的 4180 J/(kg·K) 比热容默认值，也不能把相近液冷资料当作物性表；不会外推缺失温度或浓度。"
)

ANALOGY_BOUNDARY_TEMPLATE = (
    "结论：该问题中的两个对象没有直接工程关系，不能把日常场景作为液冷设计、计算或可靠性判断依据。\n\n"
    "类比说明：如果只是教学类比，可以用日常通行、排队或流动受阻来帮助理解冷却液流动受通道约束，"
    "但该类比只用于理解，不能用于工程计算。\n\n"
    "边界说明：当前系统仅能基于液冷散热知识库给出工程解释，不能作为工程设计结论。"
)

FORBIDDEN_BOUNDARY_TEMPLATE = (
    "边界说明：本系统只能提供知识检索、一级工程估算、图结构表达和仿真准备检查，"
    "不替代 CFD、实验测试或工业级冷板设计。"
)

_FORBIDDEN_PATTERNS = (
    re.compile(r"(?:本系统)?(?:可以|可|能够)\s*替代\s*CFD", re.IGNORECASE),
    re.compile(r"不需要\s*CFD", re.IGNORECASE),
    re.compile(r"可以直接用于工程实施", re.IGNORECASE),
    re.compile(r"已完成仿真", re.IGNORECASE),
    re.compile(r"CFD\s*结果表明", re.IGNORECASE),
    re.compile(r"温度场结果为[^。；;！!\n]*", re.IGNORECASE),
    re.compile(r"速度场结果为[^。；;！!\n]*", re.IGNORECASE),
    re.compile(r"压降\s*为\s*\d+(?:\.\d+)?\s*kPa", re.IGNORECASE),
    re.compile(r"泵曲线\s*为[^。；;！!\n]*", re.IGNORECASE),
    re.compile(r"厂家性能数据表明", re.IGNORECASE),
    re.compile(r"工业级冷板设计已完成", re.IGNORECASE),
    re.compile(r"[^。；;！!\n]*(?:仿真模型自动生成|真实机柜流场|真实流场|反映真实(?:机柜)?流场)[^。；;！!\n]*", re.IGNORECASE),
)


def _repair_action(critique_result: Mapping[str, Any] | None) -> str:
    if isinstance(critique_result, Mapping):
        return str(critique_result.get("repair_action") or "")
    return ""


def _has_boundary(answer: str) -> bool:
    return "不替代 CFD" in answer or "不替代工业级冷板设计" in answer


def _append_boundary(answer: str) -> tuple[bool, str, list[str]]:
    if _has_boundary(answer):
        return False, answer, ["boundary_already_present"]
    base = answer.rstrip()
    repaired = f"{base}\n\n{BOUNDARY_WARNING}" if base else BOUNDARY_WARNING
    return True, repaired, []


def _contains_forbidden(text: str) -> bool:
    return any(pattern.search(text) for pattern in _FORBIDDEN_PATTERNS)


def _remove_forbidden_claims(answer: str) -> str:
    chunks = re.split(r"(?<=[。！？!?])|\n+", answer or "")
    safe_chunks = [chunk.strip() for chunk in chunks if chunk.strip() and not _contains_forbidden(chunk)]
    if not safe_chunks:
        return FORBIDDEN_BOUNDARY_TEMPLATE
    repaired = "\n".join(safe_chunks)
    if "不替代 CFD" not in repaired:
        repaired = f"{repaired}\n\n{FORBIDDEN_BOUNDARY_TEMPLATE}"
    return repaired


def safe_repair_answer(
    query: str,
    answer: str,
    critique_result: dict,
    metadata: dict | None = None,
    sources: list[dict] | None = None,
) -> dict:
    action = _repair_action(critique_result)
    if not is_safe_repair_action(action):
        return {
            "repaired": False,
            "repair_action": action,
            "repaired_answer": answer,
            "warnings": ["repair_action_not_safe"],
            "errors": [],
        }

    warnings: list[str] = []
    policy = get_repair_policy(action)
    repaired_answer = answer
    repaired = False

    if action == "append_boundary_warning":
        repaired, repaired_answer, warnings = _append_boundary(answer or "")
    elif action == "replace_with_property_lookup_insufficient_source_template":
        repaired = True
        repaired_answer = PROPERTY_LOOKUP_INSUFFICIENT_SOURCE_TEMPLATE
    elif action == "replace_with_analogy_boundary_template":
        repaired = True
        repaired_answer = ANALOGY_BOUNDARY_TEMPLATE
    elif action == "remove_forbidden_claims":
        candidate = _remove_forbidden_claims(answer or "")
        repaired = candidate != (answer or "")
        repaired_answer = candidate

    return {
        "repaired": repaired,
        "repair_action": action,
        "repaired_answer": repaired_answer,
        "warnings": warnings,
        "errors": [],
        "policy": policy,
    }


__all__ = [
    "ANALOGY_BOUNDARY_TEMPLATE",
    "BOUNDARY_WARNING",
    "FORBIDDEN_BOUNDARY_TEMPLATE",
    "PROPERTY_LOOKUP_INSUFFICIENT_SOURCE_TEMPLATE",
    "safe_repair_answer",
]
