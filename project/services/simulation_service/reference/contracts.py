"""Bounded SI inputs and explicit evidence for actual reference calculations."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

from services.physics_service.contracts import PhysicsValidationResult


Positive = Annotated[StrictFloat | StrictInt, Field(gt=0, allow_inf_nan=False)]


class WallLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thickness_m: Positive
    conductivity_w_mk: Positive


class LayeredWallRequest(BaseModel):
    """SI only: metres, square metres, W/(m*K), and absolute kelvin."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    model: Literal["layered_wall_steady"] = "layered_wall_steady"
    area_m2: Positive
    left_temperature_k: Positive
    right_temperature_k: Positive
    layers: list[WallLayer] = Field(min_length=1, max_length=32)
    cells_per_layer: StrictInt = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def bounded_mesh(self):
        if len(self.layers) * self.cells_per_layer > 64:
            raise ValueError("The reference discretization is limited to 64 cells")
        return self


class ReferenceMetric(BaseModel):
    name: str
    value: float = Field(allow_inf_nan=False)
    unit: Literal["W", "K/W"]


class ReferenceHistory(BaseModel):
    name: Literal["temperature_profile"] = "temperature_profile"
    axis: Literal["position_m"] = "position_m"
    axis_unit: Literal["m"] = "m"
    unit: Literal["K"] = "K"
    points: list[tuple[float, float]]


class ReferenceResult(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    model: Literal["layered_wall_steady"] = "layered_wall_steady"
    solver_version: Literal["layered-wall-reference-v1"] = "layered-wall-reference-v1"
    backend: Literal["reference"] = "reference"
    is_mock: Literal[False] = False
    cfd_executed: Literal[False] = False
    reference_executed: bool
    status: Literal["completed", "failed"]
    input_fingerprint: str
    inputs: LayeredWallRequest
    units: dict[str, str] = Field(default_factory=lambda: {
        "area_m2": "m2", "left_temperature_k": "K", "right_temperature_k": "K",
        "layers.thickness_m": "m", "layers.conductivity_w_mk": "W/(m*K)",
    })
    metrics: list[ReferenceMetric] = Field(default_factory=list)
    histories: list[ReferenceHistory] = Field(default_factory=list)
    layer_resistances_k_w: list[float] = Field(default_factory=list)
    formulas: dict[str, str] = Field(default_factory=lambda: {
        "layer_resistance": "R_i = L_i / (k_i * A)",
        "analytic_heat_rate": "Q = (T_left - T_right) / sum(R_i)",
        "nodal_equation": "sum_j ((T_i - T_j) / R_ij) = 0",
        "direction": "Positive Q flows from the left boundary to the right boundary.",
    })
    verification: dict = Field(default_factory=dict)
    validation: PhysicsValidationResult | None = None
    errors: list[dict[str, str]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=lambda: [
        "Steady one-dimensional conduction, constant conductivity per layer, uniform area, perfect interfaces, and no volumetric heat generation.",
        "Does not solve fluid flow, radiation, contact resistance, phase change, transient response, or temperature-dependent properties.",
        "Closed-form comparison and conservation check this idealized numerical model, not an actual manufactured design or a CFD solution.",
        "Absolute boundary temperatures must be strictly above 0 K; all parameters use the stated SI units without conversion.",
    ])
