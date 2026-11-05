"""Task understanding package for ThermalAgent.

The compatibility entry point remains
``services.retrieval_service.task_understanding``.
"""

from .analysis_intent import detect_analysis_intent
from .calculation_intent import detect_calculation_intent, is_calculation_request, is_lookup_range_query
from .contracts import EntityMention
from .entity_extractor import extract_entities
from .hydraulics_intent import detect_hydraulics_intent
from .hydraulic_network_intent import detect_hydraulic_network_intent
from .thermal_network_intent import detect_thermal_network_intent
from .intent_classifier import build_intent, classify_task_type
from .model_guardrail import validate_model_task_result
from .model_assist import ModelTaskUnderstandingResult, classify_task_with_model
from .model_prompt import build_task_understanding_prompt
from .normalizer import normalize_query
from .property_lookup import detect_property_lookup, is_irrelevant_or_analogy_query, is_property_lookup_query
from .shadow_mode import build_task_model_assist_metadata
from .task_types import TASK_TYPES, TaskUnderstandingResult
from .task_understanding_service import understand_task
from .visualization_intent import detect_visualization_intent

__all__ = [
    "TASK_TYPES",
    "EntityMention",
    "ModelTaskUnderstandingResult",
    "TaskUnderstandingResult",
    "build_task_model_assist_metadata",
    "build_intent",
    "build_task_understanding_prompt",
    "classify_task_with_model",
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
    "validate_model_task_result",
]
