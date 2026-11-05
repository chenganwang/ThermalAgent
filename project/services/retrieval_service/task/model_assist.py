from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .model_guardrail import validate_model_task_result
from .model_prompt import build_task_understanding_prompt


@dataclass(frozen=True)
class ModelTaskUnderstandingResult:
    """Structured model-assisted task understanding result.

    Results are safe for offline evaluation and shadow metadata only. They are
    never used for routing in this module.
    """

    enabled: bool
    model_available: bool
    used_for_routing: bool
    task_type: str | None
    confidence: float | None
    candidate_tools: list[str] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)
    raw_output: Any = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _result(
    *,
    enabled: bool,
    model_available: bool,
    task_type: str | None = None,
    confidence: float | None = None,
    candidate_tools: list[str] | None = None,
    flags: dict[str, bool] | None = None,
    raw_output: Any = None,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return ModelTaskUnderstandingResult(
        enabled=enabled,
        model_available=model_available,
        used_for_routing=False,
        task_type=task_type,
        confidence=confidence,
        candidate_tools=candidate_tools or [],
        flags=flags or {},
        raw_output=raw_output,
        warnings=warnings or [],
        error=error,
    ).to_dict()


def _local_base_url_allowed(base_url: str) -> bool:
    parsed = urllib_parse.urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _parse_model_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _call_ollama_generate(
    query: str,
    context: dict[str, Any] | None,
    *,
    model_name: str,
    base_url: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    prompt = build_task_understanding_prompt(query, context)
    endpoint = base_url.rstrip("/") + "/api/generate"
    payload = json.dumps({"model": model_name, "prompt": prompt, "stream": False, "format": "json"}).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8", errors="replace")

    outer = _parse_model_json(body)
    if outer is None:
        return validate_model_task_result(body, query=query)
    raw_response = outer.get("response", outer)
    if isinstance(raw_response, str):
        parsed_response = _parse_model_json(raw_response)
        if parsed_response is None:
            return validate_model_task_result(raw_response, query=query)
        return validate_model_task_result(parsed_response, query=query)
    return validate_model_task_result(raw_response, query=query)


def classify_task_with_model(
    query: str,
    context: dict[str, Any] | None = None,
    enable_model: bool = False,
    provider: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Optionally classify a query with a local model for offline evaluation.

    The model path is disabled by default and all successful model output goes
    through schema guardrails. The result is never used for routing.
    """

    if not enable_model:
        return _result(
            enabled=False,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["model_assist_disabled"],
            error=None,
        )

    if not _truthy(os.environ.get("TASK_MODEL_ASSIST_ENABLED")):
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["disabled_by_config", "model_adapter_not_configured"],
            error=None,
        )

    raw_provider = provider or os.environ.get("TASK_MODEL_ASSIST_PROVIDER")
    if not raw_provider:
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["missing_model_assist_provider", "model_adapter_not_configured"],
            error="missing_model_assist_provider",
        )

    selected_provider = raw_provider.strip().lower()
    if selected_provider != "ollama":
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["unsupported_provider"],
            error="unsupported_provider",
        )

    selected_model = model_name or os.environ.get("TASK_MODEL_ASSIST_MODEL")
    if not selected_model:
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["missing_model_assist_model", "model_adapter_not_configured"],
            error="missing_model_assist_model",
        )

    selected_base_url = base_url or os.environ.get("TASK_MODEL_ASSIST_BASE_URL")
    if not selected_base_url:
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["missing_model_assist_base_url", "model_adapter_not_configured"],
            error="missing_model_assist_base_url",
        )
    if not _local_base_url_allowed(selected_base_url):
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["non_local_base_url_rejected"],
            error="non_local_base_url_rejected",
        )

    try:
        selected_timeout = int(timeout_seconds or os.environ.get("TASK_MODEL_ASSIST_TIMEOUT_SECONDS") or 20)
    except (TypeError, ValueError):
        selected_timeout = 20
    selected_timeout = max(1, min(120, selected_timeout))

    try:
        guarded = _call_ollama_generate(
            query,
            context,
            model_name=selected_model,
            base_url=selected_base_url,
            timeout_seconds=selected_timeout,
        )
    except (TimeoutError, OSError, urllib_error.URLError):
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["model_unavailable"],
            error="model_unavailable",
        )
    except Exception as exc:
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            warnings=["model_adapter_error"],
            error=f"model_adapter_error:{exc.__class__.__name__}",
        )

    if guarded.get("error") == "invalid_json":
        return _result(
            enabled=True,
            model_available=False,
            task_type=None,
            confidence=None,
            raw_output=guarded.get("raw_output"),
            warnings=list(guarded.get("warnings") or ["invalid_json"]),
            error="invalid_json",
        )

    guarded["enabled"] = True
    guarded["model_available"] = True
    guarded["used_for_routing"] = False
    return guarded
