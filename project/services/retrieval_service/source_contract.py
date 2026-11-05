from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any


_TEXT_FIELDS = ("content", "snippet", "text_preview")
_LOCAL_ABSOLUTE_PATH = re.compile(r"(?i)(?:^|[\s\"'])(?:[a-z]:\\\\)")
_MAX_CONTRACT_TEXT_LENGTH = 10_000


def normalize_source_for_contract(source: Any) -> dict[str, Any]:
    """Copy a source card without inventing, deleting, or renaming fields."""

    if not isinstance(source, dict):
        return {}
    return deepcopy(source)


def validate_source_contract(source: Any) -> list[str]:
    """Return source-card contract errors without mutating the source."""

    if not isinstance(source, dict):
        return ["source_must_be_dict"]

    errors: list[str] = []
    score = source.get("score")
    if score is not None:
        try:
            float(score)
        except (TypeError, ValueError):
            errors.append("score_must_be_numeric")

    metadata = source.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata_must_be_dict")

    for field in _TEXT_FIELDS:
        value = source.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            errors.append(f"{field}_must_be_string")
        elif len(value) > _MAX_CONTRACT_TEXT_LENGTH:
            errors.append(f"{field}_too_large")

    try:
        serialized = json.dumps(source, ensure_ascii=False)
    except (TypeError, ValueError):
        errors.append("source_must_be_json_serializable")
    else:
        if _LOCAL_ABSOLUTE_PATH.search(serialized):
            errors.append("local_absolute_path_not_allowed")
    return errors


def ensure_sources_list(sources: Any) -> list[dict[str, Any]]:
    """Return copied dict source cards while safely rejecting non-list input."""

    if not isinstance(sources, (list, tuple)):
        return []
    return [normalize_source_for_contract(source) for source in sources if isinstance(source, dict)]


__all__ = [
    "ensure_sources_list",
    "normalize_source_for_contract",
    "validate_source_contract",
]
