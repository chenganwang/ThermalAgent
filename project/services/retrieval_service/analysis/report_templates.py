from __future__ import annotations

from copy import deepcopy
from typing import Any

from .report_template_contracts import ReportTemplate


def _hints(*, tables: bool, graph_slots: list[str], warning_blocks: list[str]) -> dict[str, Any]:
    return {
        "preferred_renderer": "markdown",
        "heading_level": 2,
        "table_preferred": tables,
        "graph_slots": list(graph_slots),
        "warning_blocks": list(warning_blocks),
        "export_formats": ["markdown"],
    }


DEFAULT_ENGINEERING_REPORT = ReportTemplate(
    template_id="default_engineering_report",
    name="Default engineering report",
    description="General thermal engineering analysis structure.",
    report_type="engineering",
    required_sections=[
        "problem_summary", "known_inputs", "retrieval_evidence", "calculation_summary",
        "property_lookup_summary", "engineering_analysis", "limitations", "next_steps",
    ],
    optional_sections=["visualization", "simulation_readiness", "comparison"],
    render_hints=_hints(tables=True, graph_slots=["thermal_path"], warning_blocks=["limitations", "missing_inputs"]),
    metadata_schema={"generated": "bool", "content": "string|null", "sections": "list"},
    audience="thermal_engineer",
)

SCHOOL_PROJECT_REPORT = ReportTemplate(
    template_id="school_project_report",
    name="School project report",
    description="Academic project structure without inventing experiment or CFD results.",
    report_type="school_project",
    required_sections=[
        "project_background", "objective", "technical_route", "system_architecture",
        "analysis_process", "calculation_or_tools", "result_summary",
        "risk_and_limitations", "future_work",
    ],
    optional_sections=["retrieval_evidence", "appendix"],
    render_hints=_hints(tables=True, graph_slots=["system_architecture", "thermal_path"], warning_blocks=["risk_and_limitations"]),
    metadata_schema={"generated": "bool", "content": "string|null", "sections": "list"},
    audience="student_and_reviewer",
)

COMPARISON_REPORT = ReportTemplate(
    template_id="comparison_report",
    name="Comparison report",
    description="Evidence-oriented comparison structure.",
    report_type="comparison",
    required_sections=[
        "compared_options", "evaluation_dimensions", "evidence_summary", "calculation_summary",
        "pros_cons", "recommendation", "limitations",
    ],
    optional_sections=["decision_matrix", "next_steps"],
    render_hints=_hints(tables=True, graph_slots=[], warning_blocks=["limitations"]),
    metadata_schema={"generated": "bool", "options": "list", "criteria": "list"},
    audience="engineering_decision_maker",
)

SIMULATION_READINESS_REPORT = ReportTemplate(
    template_id="simulation_readiness_report",
    name="Simulation readiness report",
    description="Pre-processing readiness structure; never a solver-result report.",
    report_type="simulation_readiness",
    required_sections=[
        "model_file_status", "geometry_status", "material_requirements", "heat_source_requirements",
        "boundary_condition_requirements", "coolant_loop_requirements", "solver_goal",
        "missing_inputs", "readiness_decision",
    ],
    optional_sections=["mesh_requirements", "property_data_requirements"],
    render_hints=_hints(tables=True, graph_slots=["model_overview"], warning_blocks=["missing_inputs", "not_run_boundary"]),
    metadata_schema={"generated": "bool", "checklist": "list", "cfd_executed": "false"},
    audience="simulation_engineer",
)

REPORT_TEMPLATES = {
    item.template_id: item
    for item in (DEFAULT_ENGINEERING_REPORT, SCHOOL_PROJECT_REPORT, COMPARISON_REPORT, SIMULATION_READINESS_REPORT)
}


def apply_report_template(report: dict[str, Any], template: ReportTemplate) -> dict[str, Any]:
    """Attach structural hints while preserving the existing report body and sections."""

    packaged = deepcopy(report or {"generated": False})
    existing_hints = packaged.get("render_hints") if isinstance(packaged.get("render_hints"), dict) else {}
    packaged["template_id"] = template.template_id
    packaged["report_type"] = template.report_type
    packaged["render_hints"] = {**deepcopy(template.render_hints), **deepcopy(existing_hints)}
    packaged["template"] = {
        "template_id": template.template_id,
        "name": template.name,
        "audience": template.audience,
        "default_format": template.default_format,
        "required_sections": list(template.required_sections),
        "optional_sections": list(template.optional_sections),
    }
    packaged.setdefault("warnings", [])
    return packaged


__all__ = [
    "COMPARISON_REPORT", "DEFAULT_ENGINEERING_REPORT", "REPORT_TEMPLATES",
    "SCHOOL_PROJECT_REPORT", "SIMULATION_READINESS_REPORT", "apply_report_template",
]
