from __future__ import annotations

import re


def classify_confirmation(query: str, explicit_action: str | None = None) -> str:
    if explicit_action in {"confirm", "cancel", "revise", "status", "plan"}:
        return explicit_action
    text = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if not text:
        return "none"
    if any(phrase in text for phrase in ("不要执行", "不要立即执行", "不执行", "只看方案", "仅看方案")):
        return "none"
    if any(phrase in text for phrase in ("取消仿真", "取消模拟", "取消计划", "终止计划")):
        return "cancel"
    if any(phrase in text for phrase in ("重新规划", "修改方案", "修订方案", "重新生成方案")):
        return "revise"
    if re.fullmatch(
        r"(?:确认(?:并)?执行|确认方案|开始执行|执行这个仿真|按这个计划运行|确认运行仿真|"
        r"confirm simulation|run this simulation|执行(?:\s+plan-[\w-]+)?|run(?:\s+plan-[\w-]+)?)。?",
        text,
    ):
        return "confirm"
    return "none"


__all__ = ["classify_confirmation"]
