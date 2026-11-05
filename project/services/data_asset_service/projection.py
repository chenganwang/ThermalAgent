from __future__ import annotations

from copy import deepcopy
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any, Iterable, Mapping

from .contracts import AssetDescriptor


class ProjectionLevel(str, Enum):
    LLM_SAFE = "llm_safe"
    ADMIN_SAFE = "admin_safe"
    INTERNAL_SERVICE = "internal_service"


_DROP = object()
_WINDOWS_PATH = re.compile(r"(?i)(?:^|\s|[('])(?>[A-Z]:[\\/])[^\s\"'<>]+")
_UNC_PATH = re.compile(r"(?:^|\s)\\\\[^\s\\]+\\[^\s]+")
_POSIX_PATH = re.compile(r"(?:^|\s)/(?!/)[^\s\"'<>]+")
_FILE_URI = re.compile(r"(?i)file://[^\s\"'<>]+")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|credential|api[_-]?key|private[_-]?key)\s*[:=]\s*\S+"
)

_SECRET_KEY_TOKENS = frozenset({
    "password", "passwd", "secret", "token", "credential", "credentials", "api_key", "apikey",
    "private_key", "access_key", "admin_token", "workflow_token", "db_password", "mysql_password",
})
_PATH_KEYS = frozenset({
    "path", "local_path", "absolute_path", "artifact_path", "filesystem_path", "storage_root",
    "project_root", "evidence_path", "source_locator", "matlab_exe", "matlab_root", "engine_python_dir",
    "block_path", "library_path", "script_path", "workspace_path",
})
_EXECUTABLE_KEYS = frozenset({"command", "shell", "stack_trace", "traceback", "raw_stack_trace", "matlab_eval"})
_INTERNAL_LOCATOR_KEYS = frozenset({"resource_locator", "artifact_resolver_key", "revision_ref"})

_SOURCE_SAFE_KEYS = frozenset({
    "rank", "doc_id", "document_id", "chunk_id", "chunk_index", "title", "book_title", "chapter",
    "section", "section_path", "page_start", "page_end", "chunk_type", "doc_type", "organization",
    "language", "publish_year", "source", "url", "score", "text_preview",
})

_LLM_DESCRIPTOR_KEYS = frozenset({
    "asset_type", "asset_id", "domain", "role", "schema_version", "version", "content_hash", "hash_status",
    "title", "summary", "origin", "retention", "immutability", "frozen", "provenance_status",
    "training_eligibility", "metadata", "provenance",
})
_ADMIN_DESCRIPTOR_KEYS = _LLM_DESCRIPTOR_KEYS | frozenset({"created_at", "updated_at", "provenance"})
_INTERNAL_DESCRIPTOR_KEYS = _ADMIN_DESCRIPTOR_KEYS

_LLM_METADATA_KEYS = frozenset({
    "display_name", "title", "summary", "source_label", "public_metadata", "capabilities", "model_id",
    "model_revision_id", "matlab_version", "execution_type", "verification_status", "validation_status",
    "release_status", "active", "index_type", "chunk_count", "artifact_count", "purpose", "tags",
    "schema_version", "version", "content_hash", "provenance_status", "hash_status", "status", "units",
})


def _normalized_key(key: Any) -> str:
    return str(key or "").strip().casefold().replace("-", "_")


def _is_secret_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return normalized in _SECRET_KEY_TOKENS or any(
        normalized.endswith(f"_{token}") for token in _SECRET_KEY_TOKENS
    )


def _is_path_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return normalized in _PATH_KEYS or normalized.endswith("_path") or normalized.endswith("_root")


def _looks_absolute_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return (
        text.casefold().startswith("file:")
        or PureWindowsPath(text).is_absolute()
        or PurePosixPath(text).is_absolute()
        or bool(_WINDOWS_PATH.search(text))
        or bool(_UNC_PATH.search(text))
        or bool(_POSIX_PATH.search(text))
    )


def _redact_text(value: str, *, allow_locator: bool) -> str | object:
    text = str(value)
    if _BEARER.search(text) or _SECRET_ASSIGNMENT.search(text):
        return _DROP
    if not allow_locator and _looks_absolute_path(text):
        text = _WINDOWS_PATH.sub(" [redacted]", text)
        text = _UNC_PATH.sub(" [redacted]", text)
        text = _POSIX_PATH.sub(" [redacted]", text)
        text = _FILE_URI.sub("[redacted]", text)
        if _looks_absolute_path(text):
            return _DROP
    return text


def _project_nested(
    value: Any,
    level: ProjectionLevel,
    *,
    allowed_keys: frozenset[str] | None,
    allow_internal_fields: frozenset[str],
) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = _normalized_key(key)
            if _is_secret_key(normalized) or normalized in _EXECUTABLE_KEYS:
                continue
            if _is_path_key(normalized):
                continue
            if normalized in _INTERNAL_LOCATOR_KEYS:
                if level is not ProjectionLevel.INTERNAL_SERVICE or normalized not in allow_internal_fields:
                    continue
            elif allowed_keys is not None and normalized not in allowed_keys:
                continue
            projected = _project_nested(
                raw_value,
                level,
                allowed_keys=allowed_keys if normalized in {"metadata", "public_metadata"} else None,
                allow_internal_fields=allow_internal_fields,
            )
            if projected is not _DROP:
                result[key] = projected
        return result
    if isinstance(value, (list, tuple, set)):
        items: list[Any] = []
        for item in value:
            projected = _project_nested(
                item,
                level,
                allowed_keys=allowed_keys,
                allow_internal_fields=allow_internal_fields,
            )
            if projected is not _DROP:
                items.append(projected)
        return items
    if isinstance(value, str):
        return _redact_text(value, allow_locator=level is ProjectionLevel.INTERNAL_SERVICE)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def project_mapping(
    payload: Mapping[str, Any],
    level: ProjectionLevel | str,
    *,
    allowed_llm_keys: Iterable[str] | None = None,
    allow_internal_fields: Iterable[str] = (),
) -> dict[str, Any]:
    """Project one mapping through an allowlist-first, recursive disclosure boundary."""

    try:
        normalized_level = ProjectionLevel(level)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported projection level: {level!r}") from exc
    allowed_internal = frozenset(_normalized_key(item) for item in allow_internal_fields)
    if normalized_level is ProjectionLevel.LLM_SAFE:
        allowed = frozenset(_normalized_key(item) for item in (allowed_llm_keys or _LLM_METADATA_KEYS))
    else:
        allowed = None
    result = _project_nested(
        deepcopy(dict(payload or {})),
        normalized_level,
        allowed_keys=allowed,
        allow_internal_fields=allowed_internal,
    )
    return dict(result) if isinstance(result, dict) else {}


def _project_descriptor_scalars(
    raw: Mapping[str, Any],
    keys: frozenset[str],
    level: ProjectionLevel,
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for key in keys.difference({"metadata", "provenance"}):
        projected = _project_nested(
            raw.get(key),
            level,
            allowed_keys=None,
            allow_internal_fields=frozenset(),
        )
        if projected is not _DROP:
            selected[key] = projected
    return selected


def project_descriptor(descriptor: AssetDescriptor, level: ProjectionLevel | str) -> dict[str, Any]:
    try:
        normalized_level = ProjectionLevel(level)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported projection level: {level!r}") from exc
    raw = descriptor.to_dict()
    if normalized_level is ProjectionLevel.LLM_SAFE:
        selected = _project_descriptor_scalars(raw, _LLM_DESCRIPTOR_KEYS, normalized_level)
        selected["metadata"] = project_mapping(raw.get("metadata") or {}, normalized_level)
        selected["provenance"] = project_mapping(
            raw.get("provenance") or {},
            normalized_level,
            allowed_llm_keys={
                "status", "origin", "source_asset_ref", "parent_asset_ref", "parent_revision_ref",
                "generation_method", "created_at", "software_version", "schema_version", "content_hash",
            },
        )
        return selected
    if normalized_level is ProjectionLevel.ADMIN_SAFE:
        selected = _project_descriptor_scalars(raw, _ADMIN_DESCRIPTOR_KEYS, normalized_level)
        selected["metadata"] = project_mapping(raw.get("metadata") or {}, normalized_level)
        selected["provenance"] = project_mapping(raw.get("provenance") or {}, normalized_level)
        selected["descriptor_hash"] = descriptor.descriptor_hash()
        return selected
    selected = _project_descriptor_scalars(raw, _INTERNAL_DESCRIPTOR_KEYS, normalized_level)
    selected["metadata"] = project_mapping(
        raw.get("metadata") or {},
        normalized_level,
        allow_internal_fields=_INTERNAL_LOCATOR_KEYS,
    )
    selected["provenance"] = project_mapping(raw.get("provenance") or {}, normalized_level)
    selected["descriptor_hash"] = descriptor.descriptor_hash()
    return selected


def project_retrieval_source(
    source: Mapping[str, Any],
    level: ProjectionLevel | str = ProjectionLevel.LLM_SAFE,
) -> dict[str, Any]:
    """Return a citation-useful source without filesystem or credential disclosure."""

    try:
        normalized_level = ProjectionLevel(level)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported projection level: {level!r}") from exc
    raw = dict(source or {})
    if normalized_level is ProjectionLevel.INTERNAL_SERVICE:
        return project_mapping(raw, normalized_level, allow_internal_fields=_INTERNAL_LOCATOR_KEYS)
    selected = {key: raw.get(key) for key in _SOURCE_SAFE_KEYS if key in raw}
    source_value = selected.get("source")
    if isinstance(source_value, str) and _looks_absolute_path(source_value):
        candidate = PureWindowsPath(source_value).name or PurePosixPath(source_value).name
        selected["source"] = str(raw.get("title") or raw.get("book_title") or candidate or "source")
    if isinstance(selected.get("url"), str) and not selected["url"].casefold().startswith(("http://", "https://")):
        selected.pop("url", None)
    return project_mapping(selected, normalized_level, allowed_llm_keys=_SOURCE_SAFE_KEYS)


__all__ = [
    "ProjectionLevel",
    "project_descriptor",
    "project_mapping",
    "project_retrieval_source",
]
