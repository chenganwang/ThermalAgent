from __future__ import annotations

from typing import Any, Sequence

from .formula_registry import FormulaRegistry, get_default_formula_registry
from .formula_schemas import FormulaRecord
from .provenance import format_provenance_zh


def lookup_formula(
    query: str,
    *,
    task_type: str | None = None,
    registry: FormulaRegistry | None = None,
) -> FormulaRecord | None:
    active = registry or get_default_formula_registry()
    return active.find_formula(query, task_type=task_type)


def answer_formula_query(
    query: str,
    *,
    task_type: str | None = None,
    registry: FormulaRegistry | None = None,
    sources: Sequence[dict[str, Any]] | None = None,
) -> str | None:
    record = lookup_formula(query, task_type=task_type, registry=registry)
    if record is None:
        return None
    return format_formula_answer(record, sources=sources)


def format_formula_answer(record: FormulaRecord, *, sources: Sequence[dict[str, Any]] | None = None) -> str:
    lines = [
        f"结论：{record.name_zh}：{record.physical_meaning_zh}",
        "",
        f"公式：{record.expression}",
    ]
    if record.latex and record.latex != record.expression:
        lines.append(f"LaTeX：{record.latex}")

    lines.extend(["", "参数含义："])
    for variable in record.variables:
        desc = f"，{variable.description_zh}" if variable.description_zh else ""
        required = "" if variable.required else "，可选"
        lines.append(f"- {variable.symbol}：{variable.name_zh}，单位 {variable.unit}{required}{desc}。")

    if record.criteria_zh:
        lines.extend(["", "判据/常用关系："])
        lines.extend(f"- {item}" for item in record.criteria_zh)

    lines.extend(["", "基本假设："])
    lines.extend(f"- {item}" for item in record.assumptions_zh)

    lines.extend(["", "适用范围："])
    lines.extend(f"- {item}" for item in record.applicability_zh)

    lines.extend(["", "边界："])
    lines.extend(f"- {item}" for item in record.limitations_zh)

    if record.tool_id:
        lines.extend(["", f"工具映射：若问题包含完整数值输入，可路由到 `{record.tool_id}`；当前回答只解释公式，不执行计算。"])
    else:
        lines.extend(["", "工具映射：当前没有确定性计算工具直接绑定该公式，回答只做公式说明。"])

    if record.engineering_notes_zh:
        lines.extend(["", "工程说明："])
        lines.extend(f"- {item}" for item in record.engineering_notes_zh)

    lines.extend(["", format_provenance_zh(record.provenance)])
    if sources:
        lines.append("检索说明：本公式答案来自本地公式注册表；未把不相关液冷资料当作公式来源。")
    else:
        lines.append("检索说明：本次没有依赖普通 chunk 检索；公式答案来自本地公式注册表。")
    return "\n".join(lines)


__all__ = ["answer_formula_query", "format_formula_answer", "lookup_formula"]
