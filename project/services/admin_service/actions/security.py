from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from services.admin_service.contracts import AdminAPIError
from services.admin_service.redaction import is_sensitive_key, redact_admin_text


DANGEROUS_PARAMETER_FIELDS = frozenset(
    {
        "command",
        "cmd",
        "shell",
        "powershell",
        "sql",
        "query_sql",
        "query",
        "python",
        "code",
        "script",
        "module_path",
        "handler",
        "function",
        "class",
        "import",
        "path",
        "file_path",
        "directory",
        "executable",
        "url",
    }
)


def reject_dangerous_parameters(value: Any, *, _depth: int = 0) -> None:
    if _depth > 12:
        raise AdminAPIError(
            "ADMIN_ACTION_PARAMETER_INVALID",
            "Action parameters exceed the supported nesting depth.",
            status_code=422,
        )
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            if key in DANGEROUS_PARAMETER_FIELDS or key.endswith("_path"):
                raise AdminAPIError(
                    "ADMIN_ACTION_PARAMETER_FORBIDDEN",
                    "Action parameters contain a forbidden field.",
                    status_code=422,
                    details={"field": key},
                )
            reject_dangerous_parameters(item, _depth=_depth + 1)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            reject_dangerous_parameters(item, _depth=_depth + 1)


def validate_action_parameters(model: type[BaseModel], parameters: Mapping[str, Any]) -> dict[str, Any]:
    reject_dangerous_parameters(parameters)
    try:
        validated = model.model_validate(dict(parameters), strict=True)
    except ValidationError as exc:
        fields = [
            {
                "location": [str(item) for item in error.get("loc") or ()],
                "type": str(error.get("type") or "validation_error"),
            }
            for error in exc.errors()
        ]
        raise AdminAPIError(
            "ADMIN_ACTION_PARAMETER_INVALID",
            "Action parameter validation failed.",
            status_code=422,
            details={"fields": fields},
        ) from exc
    return validated.model_dump(mode="json")


def sanitize_action_value(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 12:
        return "[truncated]"
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= 200:
                result["truncated"] = True
                break
            key = str(raw_key)[:128]
            if is_sensitive_key(key):
                continue
            result[key] = sanitize_action_value(item, _depth=_depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [sanitize_action_value(item, _depth=_depth + 1) for item in items[:200]]
        if len(items) > 200:
            result.append("[truncated]")
        return result
    if isinstance(value, str):
        return redact_admin_text(value)[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"[{type(value).__name__}]"


def summarize_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_action_value(dict(parameters))


__all__ = [
    "DANGEROUS_PARAMETER_FIELDS",
    "reject_dangerous_parameters",
    "sanitize_action_value",
    "summarize_parameters",
    "validate_action_parameters",
]
