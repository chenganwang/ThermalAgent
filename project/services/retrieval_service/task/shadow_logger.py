from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path("runtime") / "task_model_assist_logs" / "task_model_assist_shadow.jsonl"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        if isinstance(mapped, dict):
            return mapped
    return {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def build_task_model_assist_log_record(
    query: str,
    rule_result: dict[str, Any],
    task_model_assist: dict[str, Any],
    source: str = "agent_answer",
) -> dict[str, Any]:
    """Build a safe lightweight shadow-mode log record.

    The record intentionally excludes full answers, sources, source previews,
    and model raw output. It is for later scoring, not for routing.
    """

    rule = _as_dict(rule_result)
    shadow = _as_dict(task_model_assist)
    query_preview = str(query or "").strip()[:160]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_preview": query_preview,
        "source": str(source or "agent_answer"),
        "rule_task_type": shadow.get("rule_task_type", rule.get("task_type")),
        "model_task_type": shadow.get("model_task_type"),
        "rule_candidate_tools": _list(shadow.get("rule_candidate_tools") or rule.get("candidate_tools")),
        "model_candidate_tools": _list(shadow.get("model_candidate_tools")),
        "disagreement_with_rule": bool(shadow.get("disagreement_with_rule")),
        "disagreement_fields": _list(shadow.get("disagreement_fields")),
        "confidence": shadow.get("confidence"),
        "used_for_routing": False,
        "model_available": bool(shadow.get("model_available")),
        "model_enabled_by_config": bool(shadow.get("model_enabled_by_config")),
        "warnings": _list(shadow.get("warnings")),
        "error": shadow.get("error"),
        "rule_flags": _as_dict(shadow.get("rule_flags")),
        "model_flags": _as_dict(shadow.get("model_flags")),
        "guardrail_applied": bool(shadow.get("guardrail_applied")),
    }


def append_task_model_assist_log(record: dict[str, Any], path: str | None = None) -> bool:
    """Append a JSONL shadow log record. Return False on any write failure."""

    try:
        log_path = Path(path) if path else DEFAULT_LOG_PATH
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_as_dict(record), ensure_ascii=False, separators=(",", ":")) + "\n")
        return True
    except Exception:
        return False


__all__ = [
    "DEFAULT_LOG_PATH",
    "append_task_model_assist_log",
    "build_task_model_assist_log_record",
]
