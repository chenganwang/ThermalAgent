from __future__ import annotations


class SimulationAdapterError(Exception):
    code = "simulation_adapter_error"


class AdapterUnavailableError(SimulationAdapterError):
    code = "adapter_unavailable"


class SimulationTimeoutError(SimulationAdapterError):
    code = "simulation_timeout"


class SimulationValidationError(SimulationAdapterError):
    code = "simulation_validation_error"


class SimulationExecutionError(SimulationAdapterError):
    code = "simulation_execution_error"


class UnsupportedSimulationToolError(SimulationAdapterError):
    code = "unsupported_simulation_tool"


__all__ = [
    "AdapterUnavailableError",
    "SimulationAdapterError",
    "SimulationExecutionError",
    "SimulationTimeoutError",
    "SimulationValidationError",
    "UnsupportedSimulationToolError",
]
