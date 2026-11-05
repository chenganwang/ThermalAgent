from __future__ import annotations

from typing import Any, Mapping

from .report_template_contracts import ReportTemplate
from .report_templates import REPORT_TEMPLATES


def get_template(template_id: str) -> ReportTemplate | None:
    return REPORT_TEMPLATES.get(str(template_id or "").strip())


def list_templates() -> list[ReportTemplate]:
    return list(REPORT_TEMPLATES.values())


def validate_template(template: ReportTemplate) -> list[str]:
    errors: list[str] = []
    if not template.template_id:
        errors.append("missing_template_id")
    if not template.report_type:
        errors.append("missing_report_type")
    if not isinstance(template.required_sections, list) or not template.required_sections:
        errors.append("missing_required_sections")
    if len(template.required_sections) != len(set(template.required_sections)):
        errors.append("duplicate_required_sections")
    if not isinstance(template.render_hints, dict) or not template.render_hints:
        errors.append("missing_render_hints")
    if template.default_format != "markdown":
        errors.append("unsupported_default_format")
    return errors


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def select_template(task: Any, request: Any, metadata: Any) -> ReportTemplate:
    task_data = _mapping(task)
    request_data = _mapping(request)
    options = _mapping(request_data.get("options"))
    options = {**request_data, **options}
    metadata_data = _mapping(metadata)

    explicit = options.get("report_template_id") or options.get("report_template")
    if options.get("school_project_report") is True:
        explicit = "school_project_report"
    selected = get_template(str(explicit or ""))
    if selected is not None:
        return selected

    task_type = str(task_data.get("task_type") or "")
    simulation = _mapping(metadata_data.get("simulation"))
    comparison = _mapping(metadata_data.get("comparison"))
    if task_data.get("requires_simulation_readiness") or task_type == "simulation_readiness" or simulation.get("enabled"):
        return REPORT_TEMPLATES["simulation_readiness_report"]
    if task_data.get("requires_comparison") or task_type == "comparison" or comparison.get("generated"):
        return REPORT_TEMPLATES["comparison_report"]
    return REPORT_TEMPLATES["default_engineering_report"]


__all__ = ["get_template", "list_templates", "select_template", "validate_template"]
