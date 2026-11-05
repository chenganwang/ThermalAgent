from __future__ import annotations

from abc import ABC, abstractmethod

from .errors import SimulationAdapterError
from ..contracts import (
    SIMULATION_STATUS_FAILED,
    SimulationAdapterResult,
    SimulationRunRequest,
    SimulationToolSpec,
)
from ..schema import AdapterStatus


class SimulationAdapter(ABC):
    """Base interface for all simulation software adapters."""

    name: str
    software: str
    backend_type: str

    @property
    def adapter_name(self) -> str:
        return self.name

    def is_available(self) -> bool:
        return self.health_check().available

    def describe(self) -> dict[str, object]:
        return self.health_check().to_dict()

    def capabilities(self) -> dict[str, object]:
        return {"tools": [], "mock": False, "real_backend": False}

    def health_check(self) -> AdapterStatus:
        capabilities = self.capabilities()
        return AdapterStatus(
            adapter_name=self.adapter_name,
            available=True,
            backend_type=getattr(self, "backend_type", self.software),
            reason="available",
            capabilities=capabilities,
            supported_tools=list(capabilities.get("tools") or []),
            supports_real_backend=bool(capabilities.get("real_backend", False)),
            supports_mock=bool(capabilities.get("mock", False)),
            requires_external_software=bool(capabilities.get("requires_external_software", False)),
            external_software_name=capabilities.get("external_software_name"),
            external_software_available=not bool(capabilities.get("requires_external_software", False)),
        )

    def validate_request(self, request: SimulationRunRequest, spec: SimulationToolSpec) -> list[dict[str, object]]:
        if not self.supports(spec.tool_name):
            return [
                {
                    "code": "unsupported_simulation_tool",
                    "message": f"{self.adapter_name} does not support {spec.tool_name}.",
                }
            ]
        return []

    def supports(self, tool_name: str) -> bool:
        return tool_name in set(self.capabilities().get("tools") or [])

    def execute(self, request: SimulationRunRequest, spec: SimulationToolSpec) -> SimulationAdapterResult:
        validation_errors = self.validate_request(request, spec)
        if validation_errors:
            return SimulationAdapterResult(
                tool_name=spec.tool_name,
                adapter_name=self.adapter_name,
                status=SIMULATION_STATUS_FAILED,
                mocked=False,
                raw_result={},
                errors=validation_errors,
                backend_type=getattr(self, "backend_type", self.software),
                software=self.software,
                metadata={"cfd_executed": False, "solver_executed": False},
            )
        try:
            return self.run(request, spec)
        except SimulationAdapterError as exc:
            return SimulationAdapterResult(
                tool_name=spec.tool_name,
                adapter_name=self.adapter_name,
                status=SIMULATION_STATUS_FAILED,
                mocked=False,
                raw_result={},
                errors=[{"code": getattr(exc, "code", "simulation_adapter_error"), "message": str(exc)}],
                backend_type=getattr(self, "backend_type", self.software),
                software=self.software,
                metadata={"cfd_executed": False, "solver_executed": False},
            )

    def close(self) -> None:
        return None

    @abstractmethod
    def run(self, request: SimulationRunRequest, spec: SimulationToolSpec) -> SimulationAdapterResult:
        raise NotImplementedError


__all__ = ["SimulationAdapter"]
