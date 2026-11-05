from __future__ import annotations

from typing import Any

from ..domain_knowledge.property_query import answer_property_query
from .contracts import PropertyLookupResult


def _as_dict(result: PropertyLookupResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, PropertyLookupResult):
        return result.to_dict()
    return dict(result or {})


def format_property_lookup_result(result: PropertyLookupResult | dict[str, Any]) -> str:
    """Format property lookup output using the Phase 7A structured data wording."""

    return answer_property_query(_as_dict(result))


__all__ = ["format_property_lookup_result"]
