from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_UNIT_TYPES = {
    "concept",
    "formula",
    "parameter",
    "component",
    "thermal_path",
    "fault_case",
}

MAX_SOURCE_PREVIEW_CHARS = 300


def truncate_preview(text: Any, limit: int = MAX_SOURCE_PREVIEW_CHARS) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip()


@dataclass
class KnowledgeUnitCandidate:
    unit_type: str
    canonical_name: str
    title: str
    content: str
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    extraction_method: str = "rule_based"
    dedup_key: str = ""
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.aliases is None:
            self.aliases = []
        if self.properties is None:
            self.properties = {}
        if self.source is None:
            self.source = {}
        if self.warnings is None:
            self.warnings = []
        if self.source:
            self.source["source_text_preview"] = truncate_preview(self.source.get("source_text_preview", ""))

    def to_dict(self) -> dict[str, Any]:
        source = dict(self.source or {})
        source["source_text_preview"] = truncate_preview(source.get("source_text_preview", ""))
        return {
            "unit_type": self.unit_type,
            "canonical_name": self.canonical_name,
            "title": self.title,
            "content": self.content,
            "aliases": list(self.aliases or []),
            "properties": dict(self.properties or {}),
            "source": source,
            "confidence": float(self.confidence),
            "extraction_method": self.extraction_method or "rule_based",
            "dedup_key": self.dedup_key,
            "warnings": list(self.warnings or []),
        }
