from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReportSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    filename: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}\.out$")
    unit: Literal["K", "degC", "Pa", "W", "kg/s", "m/s", "1"]
    quantity_type: Literal["scalar", "absolute_temperature"] = "scalar"
    value_column: int = Field(default=1, ge=1, le=16)
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.quantity_type == "absolute_temperature" and self.unit not in {"K", "degC"}:
            raise ValueError("Absolute temperature requires K or degC")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class MockDemoInputs(StrictModel):
    """Declared one-dimensional plane-wall example, never an arbitrary CFD case."""

    thickness_m: FiniteFloat = Field(default=0.01, gt=0)
    conductivity_w_mk: FiniteFloat = Field(default=10.0, gt=0)
    area_m2: FiniteFloat = Field(default=0.01, gt=0)
    hot_temperature_k: FiniteFloat = Field(default=350.0, ge=0)
    cold_temperature_k: FiniteFloat = Field(default=300.0, ge=0)


class CaseSpec(StrictModel):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=120, pattern=r"^[^\r\n<>]+$")
    backend: Literal["fluent", "mock"] = "fluent"
    case_file: str | None = None
    data_file: str | None = None
    dimension: Literal["2ddp", "3ddp"] = "3ddp"
    initialize: bool = False
    reports: list[ReportSpec] = Field(default_factory=list, max_length=16)
    residual_targets: dict[str, FiniteFloat] = Field(default_factory=dict, max_length=16)
    demo_inputs: MockDemoInputs | None = None

    @model_validator(mode="after")
    def consistent_case(self):
        if self.backend == "mock":
            if self.case_file is not None or self.data_file is not None or self.initialize or self.reports or self.residual_targets:
                raise ValueError("Mock cases cannot claim Fluent files, initialization, or residual evidence")
            if self.demo_inputs is None:
                self.demo_inputs = MockDemoInputs()
            return self
        if self.demo_inputs is not None:
            raise ValueError("Fluent cases cannot contain mock demo inputs")
        if not self.data_file and not self.initialize:
            raise ValueError("A case needs reviewed initialization or an existing data file")
        if self.data_file and self.initialize:
            raise ValueError("Do not discard a supplied initial data file")
        if not self.case_file or not self.case_file.endswith(".cas.h5") or (self.data_file and not self.data_file.endswith(".dat.h5")):
            raise ValueError("Only reviewed HDF5 case/data pairs are supported")
        if len({r.name for r in self.reports}) != len(self.reports) or len({r.filename for r in self.reports}) != len(self.reports):
            raise ValueError("Report names and filenames must be unique")
        allowed = {"continuity", "x-velocity", "y-velocity", "z-velocity", "energy", "k", "epsilon", "omega"}
        if any(key not in allowed or value <= 0 for key, value in self.residual_targets.items()):
            raise ValueError("Invalid residual target")
        return self


def builtin_mock_case() -> CaseSpec:
    return CaseSpec(case_id="mock_cfd_demo", title="Mock CFD 流程演示：一维平壁解析示例", backend="mock", demo_inputs=MockDemoInputs())


class PrepareJob(StrictModel):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    iterations: int = Field(default=100, ge=1, le=10000)
    processors: int = Field(default=1, ge=1, le=64)


class RunJob(StrictModel):
    confirmed: Literal[True]
    input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Execution requires explicit boolean true confirmation")
        return value


class FluentError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def public(self) -> dict:
        return {"code": self.code, "message": self.message}
