"""Compatibility facade for deterministic local thermal tools.

Tool specs, routing, execution, and formatting live in focused modules under
``services.retrieval_service.tools``. This module keeps the original public
functions and constants import-compatible.
"""

from __future__ import annotations

from ..properties.formatter import format_property_lookup_result as format_property_lookup_answer
from ..properties.property_lookup_tool import run_property_lookup_tool
from .executor import parse_tool_inputs, run_detected_tool
from .formatter import format_tool_answer
from .router import detect_calculation_tool, detect_property_lookup_tool
from .specs import (
    REQUIRED_PARAMETERS,
    TOOL_FORMULAS,
    TOOL_FUNCTIONS,
    TOOL_NOTES,
    TOOL_SPECS,
    ToolFunc,
    ToolSpec,
)

__all__ = [
    "REQUIRED_PARAMETERS",
    "TOOL_FORMULAS",
    "TOOL_FUNCTIONS",
    "TOOL_NOTES",
    "TOOL_SPECS",
    "ToolFunc",
    "ToolSpec",
    "detect_calculation_tool",
    "detect_property_lookup_tool",
    "format_tool_answer",
    "format_property_lookup_answer",
    "parse_tool_inputs",
    "run_property_lookup_tool",
    "run_detected_tool",
]
