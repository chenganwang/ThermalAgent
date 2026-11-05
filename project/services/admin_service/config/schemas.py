from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


Reason = Annotated[str, Field(min_length=1, max_length=500)]


class ConfigPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: dict[str, StrictBool] = Field(min_length=1, max_length=4)
    expected_version: StrictInt = Field(ge=1)
    reason: Reason
    dry_run: StrictBool = False

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be empty")
        return normalized


class ConfigRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_version: StrictInt = Field(ge=1)
    expected_version: StrictInt = Field(ge=1)
    reason: Reason
    dry_run: StrictBool = False

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be empty")
        return normalized


__all__ = ["ConfigPatchRequest", "ConfigRollbackRequest"]
