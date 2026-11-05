from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any


TOP_LEVEL_FIELDS = {
    "answer", "query", "task_type", "retrieval_count", "task", "rewrite", "sources", "session_id", "metadata"
}


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchResult:
    valid: bool
    found: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_response_top_level(response: Any) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(response, dict):
        return ValidationResult(False, ["response_not_dict"])
    missing = sorted(TOP_LEVEL_FIELDS - set(response))
    if missing:
        errors.append(f"missing_top_level:{','.join(missing)}")
    sources = response.get("sources")
    if not isinstance(sources, list):
        errors.append("sources_not_list")
        sources = []
    count = response.get("retrieval_count")
    if not isinstance(count, int) or isinstance(count, bool):
        errors.append("retrieval_count_not_int")
    elif count != len(sources):
        errors.append("retrieval_count_mismatch")
    if not isinstance(response.get("metadata"), dict):
        errors.append("metadata_not_dict")
    try:
        json.dumps(response, ensure_ascii=False)
    except (TypeError, ValueError):
        errors.append("response_not_json_serializable")
    return ValidationResult(not errors, errors)


def _resolve_path(metadata: dict[str, Any], path: str) -> tuple[bool, Any]:
    parts = [part for part in str(path).split(".") if part]
    if parts and parts[0] == "metadata":
        parts = parts[1:]
    current: Any = metadata
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def validate_metadata_paths(metadata: Any, paths: list[str]) -> MatchResult:
    source = metadata if isinstance(metadata, dict) else {}
    found: list[str] = []
    missing: list[str] = []
    for path in paths:
        exists, _ = _resolve_path(source, path)
        (found if exists else missing).append(path)
    return MatchResult(not missing, found, missing)


def _collect_tool_names(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"tool_name", "calculation_tool"} and isinstance(item, str) and item:
                found.add(item)
            elif key == "candidate_tools" and isinstance(item, list):
                found.update(str(tool) for tool in item if tool)
            else:
                _collect_tool_names(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_tool_names(item, found)


def validate_expected_tools(response: Any, expected_tools: list[str]) -> MatchResult:
    observed: set[str] = set()
    if isinstance(response, dict):
        _collect_tool_names(response.get("task"), observed)
        _collect_tool_names(response.get("metadata"), observed)
    found = [name for name in expected_tools if name in observed]
    missing = [name for name in expected_tools if name not in observed]
    return MatchResult(not missing, found, missing)


def _claim_text(response: dict[str, Any]) -> str:
    safe_view = {"answer": response.get("answer"), "metadata": response.get("metadata")}
    return json.dumps(safe_view, ensure_ascii=False, default=str)


def validate_forbidden_claims(response: Any, should_not_include: list[str]) -> ValidationResult:
    if not isinstance(response, dict):
        return ValidationResult(False, ["response_not_dict"])
    text = _claim_text(response)
    errors: list[str] = []
    for phrase in should_not_include:
        if phrase and re.search(re.escape(phrase), text, flags=re.IGNORECASE):
            errors.append(f"forbidden_claim:{phrase}")
    return ValidationResult(not errors, errors)


def collect_text_matches(value: Any, needles: list[str]) -> MatchResult:
    text = json.dumps(value, ensure_ascii=False, default=str).lower()
    found = [item for item in needles if item.lower() in text]
    missing = [item for item in needles if item.lower() not in text]
    return MatchResult(not missing, found, missing)


__all__ = [
    "MatchResult", "TOP_LEVEL_FIELDS", "ValidationResult", "collect_text_matches",
    "validate_expected_tools", "validate_forbidden_claims", "validate_metadata_paths",
    "validate_response_top_level",
]
