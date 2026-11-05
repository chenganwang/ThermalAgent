"""Compatibility wrapper for the ThermalAgent orchestrator.

New code should import from services.retrieval_service.agent.thermal_agent.
This module preserves the legacy import path:
from services.retrieval_service.agent_orchestrator import ThermalAgent
"""

from __future__ import annotations

from .agent.thermal_agent import (
    AgentAnalysis,
    RetrieverFunc,
    ThermalAgent,
    _calculation_metadata,
    _default_retriever,
    _env_bool,
    _safe_error,
)

__all__ = [
    "AgentAnalysis",
    "RetrieverFunc",
    "ThermalAgent",
    "_calculation_metadata",
    "_default_retriever",
    "_env_bool",
    "_safe_error",
]
