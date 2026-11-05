from __future__ import annotations

from typing import Any

from .config import SimulationConfig, load_simulation_config
from .contracts import SimulationRunRequest
from .service import SimulationService


class SimulationToolCallingHelper:
    """Opt-in helper for future workflow/tool-calling integration.

    This helper does not modify the Agent default path. Callers must either use
    `run_explicit_request` directly or enable `SIMULATION_TOOL_CALLING_ENABLED`.
    """

    def __init__(self, *, service: SimulationService | None = None, config: SimulationConfig | None = None) -> None:
        self.config = config or load_simulation_config()
        self.service = service or SimulationService.default()

    @classmethod
    def default(cls) -> "SimulationToolCallingHelper":
        return cls()

    def run_explicit_request(self, request: SimulationRunRequest):
        return self.service.run(request)

    def maybe_run_from_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.tool_calling_enabled:
            return {"enabled": False, "called": False, "reason": "simulation_tool_calling_disabled"}
        tool_name = str(payload.get("tool_name") or "")
        if not tool_name:
            return {"enabled": True, "called": False, "reason": "missing_tool_name"}
        request = SimulationRunRequest(
            tool_name=tool_name,
            inputs=dict(payload.get("inputs") or {}),
            adapter_name=str(payload.get("adapter_name") or "mock"),
            mode=str(payload.get("mode") or "mock"),
            user_query=payload.get("user_query"),
            options=dict(payload.get("options") or {}),
        )
        envelope = self.service.run(request)
        return {"enabled": True, "called": True, "simulation_execution": envelope.to_dict()}


__all__ = ["SimulationToolCallingHelper"]
