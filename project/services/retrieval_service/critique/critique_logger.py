from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CRITIQUE_LOG_PATH = Path("runtime/critique_logs/self_critique_log.jsonl")
PREVIEW_LIMIT = 160


def _preview(value: Any, limit: int = PREVIEW_LIMIT) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _issues(self_critique: Mapping[str, Any]) -> list[dict[str, Any]]:
    original = self_critique.get("original_critique")
    if isinstance(original, Mapping) and isinstance(original.get("issues"), list):
        return [item for item in original["issues"] if isinstance(item, Mapping)]
    raw = self_critique.get("issues")
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def build_critique_log_record(
    query: str,
    task_type: str | None,
    retrieval_intent: str | None,
    template_type: str | None,
    tool_name: str | None,
    sources_count: int,
    self_critique: dict,
) -> dict[str, Any]:
    critique = self_critique if isinstance(self_critique, Mapping) else {}
    issues = _issues(critique)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_preview": _preview(query),
        "task_type": task_type,
        "retrieval_intent": retrieval_intent,
        "template_type": template_type,
        "tool_name": tool_name,
        "sources_count": int(sources_count or 0),
        "critique_severity": critique.get("severity"),
        "route": critique.get("route"),
        "final_route": critique.get("final_route"),
        "repair_action": critique.get("repair_action"),
        "repair_attempts": critique.get("repair_attempts", 0),
        "repaired": bool(critique.get("repaired")),
        "requires_human_review": bool(critique.get("requires_human_review")),
        "issue_types": sorted({str(item.get("type")) for item in issues if item.get("type")}),
    }


def append_critique_log(record: dict, path: str | None = None) -> bool:
    try:
        target = Path(path) if path else DEFAULT_CRITIQUE_LOG_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except Exception:
        return False


__all__ = ["DEFAULT_CRITIQUE_LOG_PATH", "append_critique_log", "build_critique_log_record"]
