from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReportTemplate:
    template_id: str
    name: str
    description: str
    report_type: str
    required_sections: list[str]
    optional_sections: list[str]
    render_hints: dict[str, Any]
    metadata_schema: dict[str, Any]
    audience: str
    default_format: str = "markdown"

    def __post_init__(self) -> None:
        if not str(self.template_id or "").strip():
            raise ValueError("template_id is required")
        if not str(self.report_type or "").strip():
            raise ValueError("report_type is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReportTemplateRenderResult:
    template_id: str
    report_type: str
    generated: bool
    sections: list[dict[str, Any]] = field(default_factory=list)
    content: str | None = None
    render_hints: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.template_id or "").strip():
            raise ValueError("template_id is required")
        if not str(self.report_type or "").strip():
            raise ValueError("report_type is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["ReportTemplate", "ReportTemplateRenderResult"]
