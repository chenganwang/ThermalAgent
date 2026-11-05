from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class AdminError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class AdminResponse(BaseModel):
    success: bool
    request_id: str
    data: Any = None
    error: AdminError | None = None
    warnings: list[str] = Field(default_factory=list)
    timestamp: str


class ModuleHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    name: str
    category: str
    configured: bool | None
    enabled: bool
    available: bool | None
    ready: bool | None
    healthy: bool | None
    status: str
    severity: str
    experimental: bool
    optional: bool
    last_check_at: str
    last_success_at: str | None
    latency_ms: int
    stale_after_seconds: int
    dependencies: list[str]
    metrics: dict[str, Any]
    error_code: str | None
    message: str
    next_action: str | None
    source: str
    observed_at: str
    side_effects: list[str] = Field(default_factory=list)


class AdminAPIError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})
        self.retryable = retryable


@dataclass(frozen=True)
class AdminCheckContext:
    app: Any
    cfg: Any
    project_root: Any


@dataclass(frozen=True)
class CheckOutcome:
    configured: bool | None = True
    enabled: bool = True
    available: bool | None = None
    ready: bool | None = None
    healthy: bool | None = None
    status: str | None = None
    severity: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    message: str = ""
    next_action: str | None = None


Checker = Callable[[AdminCheckContext], CheckOutcome]


@dataclass(frozen=True)
class ModuleDescriptor:
    module_id: str
    name: str
    category: str
    checker: Checker
    dependencies: tuple[str, ...] = ()
    experimental: bool = False
    optional: bool = False
    timeout_seconds: float = 2.0
    cache_ttl_seconds: int = 30
    stale_after_seconds: int = 120
    source: str = "admin_registry"


__all__ = [
    "AdminAPIError",
    "AdminCheckContext",
    "AdminError",
    "AdminResponse",
    "CheckOutcome",
    "ModuleDescriptor",
    "ModuleHealth",
]
