"""Strict public input contracts for immutable research definitions."""
from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,96}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Quantity(Contract):
    value: float
    unit: str = Field(min_length=1, max_length=24)

    @field_validator("value", mode="before")
    @classmethod
    def numeric(cls, value):
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError("Quantity value must be an explicit finite number")
        return value


class BoundaryConditions(Contract):
    mass_flow_rate: Quantity
    temperature: Quantity
    outlet_pressure: Quantity
    additional: dict[str, Any] = Field(default_factory=dict)


class ParameterSpec(Contract):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["continuous", "integer", "categorical"]
    unit: str = Field(min_length=1, max_length=24)
    lower: float | None = None
    upper: float | None = None
    choices: list[str] | None = Field(default=None, max_length=100)
    source: str = Field(min_length=1, max_length=2000)

    @field_validator("source", "name", "unit")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A nonblank value is required")
        return value.strip()

    @field_validator("lower", "upper", mode="before")
    @classmethod
    def explicit_number(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("Bounds must be explicit finite numbers")
        return value


class QualityPolicy(Contract):
    mass_balance_relative_tolerance: float = Field(default=0.01, gt=0, lt=1)


class StudyRequest(Contract):
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=4000)
    side: Literal["anode", "cathode"]
    physics_model: Literal["single_phase", "two_phase", "electrochemical"]
    model_version: str = Field(min_length=1, max_length=160)
    fluid: str = Field(min_length=1, max_length=160)
    project_id: Identifier = "local"
    parent_study_id: Identifier | None = None
    boundary_conditions: BoundaryConditions
    parameter_space: list[ParameterSpec] = Field(min_length=8, max_length=64)
    research_conditions: dict[str, Any] = Field(default_factory=dict)
    quality_policy: QualityPolicy = Field(default_factory=QualityPolicy)
    knowledge_sources: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("title", "objective", "model_version", "fluid")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A nonblank value is required")
        return value.strip()


class DOERequest(Contract):
    samples: StrictInt = Field(ge=1, le=1000)
    seed: StrictInt = Field(ge=0, le=4294967295)
    max_attempts: StrictInt = Field(default=10000, ge=1, le=100000)


class ImportRequest(Contract):
    content: str = Field(min_length=1, max_length=5_000_000)
    format: Literal["csv", "json"]
    filename: str = Field(min_length=1, max_length=200)
    provenance: Literal["fluent_export", "manual_import", "synthetic_demo"]
    field_map: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("filename")
    @classmethod
    def basename(cls, value):
        if value in {".", ".."} or any(c in value for c in "\\/:\r\n\x00"):
            raise ValueError("filename must be a plain basename")
        return value


class CompareRequest(Contract):
    result_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("result_ids")
    @classmethod
    def distinct(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Distinct result IDs are required")
        return value
