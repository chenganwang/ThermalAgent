from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    parameters: dict[str, Any] = Field(default_factory=dict)


class EmptyActionParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ActionHandlerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    success: bool = True
    summary: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ActionHandlerResult", "ActionRequest", "EmptyActionParameters"]
