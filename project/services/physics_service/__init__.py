"""Shared, deterministic engineering constraints; no solver or storage ownership."""

from .contracts import PhysicsValidationRequest, PhysicsValidationResult
from .validator import validate_physics

__all__ = ["PhysicsValidationRequest", "PhysicsValidationResult", "validate_physics"]
