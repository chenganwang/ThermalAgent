from __future__ import annotations


class SimulationServiceError(Exception):
    """Base exception for controlled Simulation Service failures."""


class SimulationConfigurationError(SimulationServiceError):
    """Raised when the simulation module is misconfigured."""


__all__ = ["SimulationConfigurationError", "SimulationServiceError"]
