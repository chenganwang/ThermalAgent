from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


TASK_TYPES = {
    "concept",
    "formula",
    "calculation",
    "retrieval",
    "comparison",
    "visualization",
    "report",
    "simulation",
    "property_lookup",
    "fault_analysis",
    "irrelevant_or_analogy",
    "unknown",
    # Legacy task types kept for existing answer/rewrite templates.
    "concept_explanation",
    "mechanism_analysis",
    "troubleshooting",
    "design_advice",
    "literature_lookup",
    "general_qa",
}


@dataclass(frozen=True)
class EntityMention:
    """Lightweight structured entity mention for future consumers."""

    text: str
    type: str = "thermal_entity"
    normalized: str | None = None
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskUnderstandingResult:
    """Rule-based task understanding result for the thermal agent.

    The first block of fields preserves the legacy public contract. The
    additional fields make downstream routing explicit without changing
    ``/agent/answer`` top-level response fields.
    """

    task_type: str
    domain: str = "thermal_management"
    entities: list[str] = field(default_factory=list)
    intent: str = ""
    needs_retrieval: bool = True
    needs_calculation: bool = False
    needs_visualization: bool = False
    confidence: float = 0.5
    original_query: str = ""
    normalized_query: str = ""
    warnings: list[str] = field(default_factory=list)

    candidate_tools: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    needs_report: bool = False
    needs_comparison: bool = False
    needs_simulation: bool = False
    is_property_lookup: bool = False
    is_irrelevant_or_analogy: bool = False
    pump_selection_requested: bool = False
    flow_distribution_requested: bool = False
    thermal_network_requested: bool = False
    bottleneck_requested: bool = False
    sensitivity_requested: bool = False
    raw_signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
