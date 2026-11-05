"""Bounded task inputs; no executable paths, programs or arbitrary tool names."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from services.retrieval_service.api.schemas import AgentAnswerRequest
from services.simulation_service.reference import LayeredWallRequest
from .design_contracts import DesignCriteria, Positive



class LiquidCoolingInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heat_load_w: Positive | None = None
    coolant_delta_t_k: Positive | None = None
    specific_heat_j_kgk: Positive | None = None
    density_kg_m3: Positive | None = None
    dynamic_viscosity_pa_s: Positive | None = None
    hydraulic_diameter_m: Positive | None = None
    length_m: Positive | None = None
    minor_loss_coefficient: Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)] | None = None


class EngineeringTaskRequest(AgentAnswerRequest):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=12000)
    session_id: str = Field(default="default", min_length=1, max_length=160)
    requested_outputs: list[str] = Field(default_factory=list, max_length=8)
    liquid_cooling: LiquidCoolingInputs | None = None
    design_criteria: DesignCriteria | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_reference_model(cls, value):
        from .task_input_parser import explicit_wall_inputs
        return explicit_wall_inputs(value)

    @model_validator(mode="after")
    def bounded_task(self):
        if not self.query.strip():
            raise ValueError("Provide an engineering question")
        if self.simulation_mode or self.simulation_action or self.simulation_plan_id or self.uploaded_model_file_id or self.uploaded_model_filename:
            raise ValueError("Simulation confirmation and uploaded models use the existing synchronous simulation interface")
        if self.reference_solver is not None and self.liquid_cooling is not None:
            raise ValueError("Choose one engineering model per task")
        if self.design_criteria is not None and self.reference_solver is None:
            from .task_workflow import is_liquid_task
            if not is_liquid_task(self.model_dump()):
                raise ValueError("Design limits require a liquid cooling or explicit reference model")
        if any(value not in {"report", "solution", "comparison", "visualization"} for value in self.requested_outputs):
            raise ValueError("This task endpoint supports local engineering outputs only")
        return self


class TaskRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1)


class TaskContinuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=12000)
    session_id: str = Field(min_length=1, max_length=160)
    current_task_id: str | None = Field(default=None, pattern=r"^task_[a-f0-9]{32}$")
    expected_revision: StrictInt | None = Field(default=None, ge=1)
    current_context_kind: Literal["engineering", "simulation", "other"] | None = None


class TaskRetry(TaskRevision):
    confirmed: StrictBool
    query: str | None = Field(default=None, min_length=1, max_length=12000)
    liquid_cooling: LiquidCoolingInputs | None = None
    design_criteria: DesignCriteria | None = None
    reference_solver: LayeredWallRequest | None = None

    @model_validator(mode="after")
    def confirmed_retry(self):
        if self.confirmed is not True:
            raise ValueError("Explicit retry confirmation is required")
        return self
