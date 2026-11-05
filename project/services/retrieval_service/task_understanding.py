"""Compatibility wrapper for legacy imports.

New code should import from
``services.retrieval_service.task.task_understanding_service``.
"""

from __future__ import annotations

from .task.analysis_intent import detect_analysis_intent
from .task.calculation_intent import detect_calculation_intent, is_calculation_request, is_lookup_range_query
from .task.contracts import EntityMention
from .task.entity_extractor import extract_entities
from .task.intent_classifier import build_intent, classify_task_type
from .task.hydraulics_intent import detect_hydraulics_intent
from .task.hydraulic_network_intent import detect_hydraulic_network_intent
from .task.thermal_network_intent import detect_thermal_network_intent
from .task.normalizer import normalize_query
from .task.property_lookup import detect_property_lookup, is_irrelevant_or_analogy_query, is_property_lookup_query
from .task.task_types import TASK_TYPES, TaskUnderstandingResult
from .task.task_understanding_service import understand_task
from .task.visualization_intent import detect_visualization_intent

__all__ = [
    "TASK_TYPES",
    "EntityMention",
    "TaskUnderstandingResult",
    "build_intent",
    "classify_task_type",
    "detect_analysis_intent",
    "detect_calculation_intent",
    "detect_hydraulics_intent",
    "detect_hydraulic_network_intent",
    "detect_thermal_network_intent",
    "detect_property_lookup",
    "detect_visualization_intent",
    "extract_entities",
    "is_calculation_request",
    "is_irrelevant_or_analogy_query",
    "is_lookup_range_query",
    "is_property_lookup_query",
    "normalize_query",
    "understand_task",
]
