"""Shared design constraints, independent of HTTP and task request schemas."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]


class DesignCriteria(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_pressure_drop_pa: Positive | None = None
    max_volume_flow_l_min: Positive | None = None
    max_thermal_resistance_k_w: Positive | None = None
    max_heat_rate_abs_w: Positive | None = None

    @model_validator(mode='after')
    def nonempty(self):
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError('Provide at least one explicit design limit')
        return self
