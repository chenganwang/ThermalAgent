from __future__ import annotations

from typing import Any


ALLOWED_MODEL_TASK_TYPES = {
    "concept",
    "formula",
    "calculation",
    "retrieval",
    "comparison",
    "visualization",
    "report",
    "simulation_readiness",
    "property_lookup",
    "fault_analysis",
    "irrelevant_or_analogy",
    "unknown",
}

ALLOWED_MODEL_CANDIDATE_TOOLS = {
    "liquid_flow_rate_required",
    "junction_temperature_estimate",
    "required_thermal_resistance",
    "conduction_resistance",
    "coolant_temperature_rise",
}


def build_task_understanding_prompt(query: str, context: dict[str, Any] | None = None) -> str:
    """Build a constrained JSON-only prompt for offline task understanding checks."""

    context = context or {}
    allowed_task_types = " | ".join(sorted(ALLOWED_MODEL_TASK_TYPES))
    allowed_tools = ", ".join(sorted(ALLOWED_MODEL_CANDIDATE_TOOLS))
    context_hint = ""
    if context.get("case_id"):
        context_hint = f"\nCase ID: {context['case_id']}"

    return (
        "You are classifying a ThermalAgent user query for offline evaluation only.\n"
        "Return JSON only. Do not include markdown, comments, explanations outside JSON, or extra text.\n"
        "Do not calculate numeric values. Do not generate an answer. Do not generate sources. "
        "Do not fabricate tool results.\n"
        "ASHRAE/OCP recommended or allowable range lookup is not an engineering calculation.\n"
        "EGW/PGW coolant property lookup is not a liquid-flow-rate calculation.\n"
        "Simulation-related queries can only be marked as simulation_readiness, never simulation_result.\n"
        f"candidate_tools can only use these names: {allowed_tools}.\n"
        f"task_type must be one of: {allowed_task_types}.\n"
        "Output schema:\n"
        "{\n"
        '  "task_type": "concept | formula | calculation | retrieval | comparison | visualization | report | '
        'simulation_readiness | property_lookup | fault_analysis | irrelevant_or_analogy | unknown",\n'
        '  "needs_calculation": false,\n'
        '  "candidate_tools": [],\n'
        '  "needs_visualization": false,\n'
        '  "needs_report": false,\n'
        '  "needs_comparison": false,\n'
        '  "needs_simulation": false,\n'
        '  "is_property_lookup": false,\n'
        '  "is_irrelevant_or_analogy": false,\n'
        '  "confidence": 0.0,\n'
        '  "reason": "brief reason"\n'
        "}\n"
        f"Query: {query}{context_hint}"
    )
