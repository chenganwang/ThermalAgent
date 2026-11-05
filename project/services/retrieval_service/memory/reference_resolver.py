from __future__ import annotations

import re
from typing import Any, Mapping


CN_REFERENCE_TOKENS = (
    "它",
    "其",
    "这个",
    "这份文件",
    "该文件",
    "这个规范",
    "该规范",
    "这个等级",
    "上面这个等级",
    "该等级",
    "这个表格",
    "该表格",
    "这种方式",
    "该方案",
    "该技术",
    "上述方案",
)


def resolve_references(query: str, context: Mapping[str, Any]) -> str:
    """Resolve common short references using session focus and entities."""

    text = query or ""
    if not text.strip():
        return text

    focus = context.get("focus")
    entities = list(context.get("entities") or [])
    if not focus and entities:
        focus = entities[-1]
    if not focus:
        return text

    focus_text = str(focus)
    resolved = text
    if any(token in resolved for token in CN_REFERENCE_TOKENS):
        for token in sorted(CN_REFERENCE_TOKENS, key=len, reverse=True):
            resolved = resolved.replace(token, focus_text)

    if re.search(r"\bit\b|\bthis\b|\bthat\b", resolved, flags=re.IGNORECASE):
        resolved = re.sub(r"\bit\b", focus_text, resolved, flags=re.IGNORECASE)
        resolved = re.sub(r"\bthis\b", focus_text, resolved, flags=re.IGNORECASE)
        resolved = re.sub(r"\bthat\b", focus_text, resolved, flags=re.IGNORECASE)

    return resolved
