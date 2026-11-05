"""Rule-based multi-agent observability layer for the staged agent pipeline."""

from .contracts import AgentRoleCard, SupervisorPlan, SupervisorRunResult, WorkerExecutionRecord
from .role_cards import get_role_card, list_role_cards
from .metadata import attach_multi_agent_metadata, default_multi_agent_metadata
from .supervisor_planner import build_supervisor_plan
from .supervisor_runner import run_supervisor_shadow
from .trace_builder import build_worker_trace
from .worker_registry import get_worker, list_workers, map_stage_to_role, validate_worker_registry

__all__ = [
    "AgentRoleCard",
    "SupervisorPlan",
    "SupervisorRunResult",
    "WorkerExecutionRecord",
    "attach_multi_agent_metadata",
    "build_supervisor_plan",
    "build_worker_trace",
    "default_multi_agent_metadata",
    "get_role_card",
    "get_worker",
    "list_role_cards",
    "list_workers",
    "map_stage_to_role",
    "run_supervisor_shadow",
    "validate_worker_registry",
]
