"""Explicit units and bounded requests for physical consistency checks."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator


Numeric = StrictFloat | StrictInt
Unit = Literal["1", "W", "K", "degC", "Pa", "kPa", "m", "m2", "m/s", "kg/s", "m3/s", "K/W", "W/m2", "W/(m*K)", "J/(kg*K)"]


class PhysicsQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    value: Numeric
    unit: Unit
    quantity_type: Literal["scalar", "absolute_temperature"] = "scalar"
    positive: bool = False
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.quantity_type == "absolute_temperature" and self.unit not in {"K", "degC"}:
            raise ValueError("Absolute temperature requires K or degC")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must be <= maximum")
        return self


class EnergyBalance(BaseModel):
    """Steady control volume, same sign convention; include losses in output."""

    model_config = ConfigDict(extra="forbid")

    heat_input_w: Numeric
    heat_output_w: Numeric
    relative_tolerance: float = Field(default=0.02, ge=0, le=1, allow_inf_nan=False)
    absolute_tolerance_w: float = Field(default=1e-6, ge=0, le=1e12, allow_inf_nan=False)


class PhysicsValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantities: list[PhysicsQuantity] = Field(default_factory=list, max_length=128)
    energy_balance: EnergyBalance | None = None

    @model_validator(mode="after")
    def has_checks(self):
        if not self.quantities and self.energy_balance is None:
            raise ValueError("Provide quantities or an energy balance to check")
        names = [item.name for item in self.quantities]
        if len(names) != len(set(names)):
            raise ValueError("Quantity names must be unique")
        return self


class PhysicsIssue(BaseModel):
    code: str
    field: str
    message: str


class PhysicsValidationResult(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    validator_version: Literal["physics-v1"] = "physics-v1"
    validation_method: Literal["deterministic_constraints"] = "deterministic_constraints"
    passed: bool
    status: Literal["passed", "failed"]
    checked_quantity_count: int
    energy_balance_checked: bool
    energy_relative_error: float | None = None
    issues: list[PhysicsIssue] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=lambda: [
        "Checks only the supplied quantities and constraints; a pass is not engineering certification.",
        "Energy balance assumes steady state and a common control volume with all losses accounted for.",
        "Units are explicit canonical units; no inference or unit conversion is performed.",
    ])
