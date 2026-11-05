from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


ASSET_STATUSES = frozenset({"quarantined", "pending_review", "approved", "rejected", "registered", "blocked", "archived"})
ASSET_TYPES = frozenset({"simulation_model", "data_asset", "geometry_asset"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ModelAsset:
    asset_id: str
    original_filename: str
    stored_filename: str
    asset_type: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: str = "quarantined"
    uploaded_at: str = field(default_factory=utc_now_iso)
    uploaded_by: str = "user"
    updated_at: str = field(default_factory=utc_now_iso)
    approved_at: str | None = None
    approved_by: str | None = None
    approved_sha256: str | None = None
    rejected_at: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    operator_notes: str | None = None
    scenario_id: str | None = None
    proposed_model_id: str | None = None
    registered_model_id: str | None = None
    execution_allowed: bool = False
    human_validated: bool = False
    security_scan_status: str = "not_scanned"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModelAsset":
        names = cls.__dataclass_fields__
        values = {name: payload[name] for name in names if name in payload}
        values["metadata"] = dict(payload.get("metadata") or {})
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetUploadResult:
    asset: ModelAsset
    bytes_written: int


@dataclass(frozen=True)
class ApprovalRequest:
    scenario_id: str
    proposed_model_id: str
    operator_notes: str = ""


@dataclass(frozen=True)
class RegistrationRequest:
    solver: str
    adapter_id: str | None
    allowed_inputs: tuple[str, ...]
    operator_confirmation: bool
    version: str = "0.1.0"
    status: str = "unvalidated"


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: str
    action: str
    asset_id: str
    previous_status: str | None
    new_status: str | None
    actor_type: str
    success: bool
    reason: str
    sensitive_fields_redacted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ASSET_STATUSES",
    "ASSET_TYPES",
    "ApprovalRequest",
    "AssetUploadResult",
    "AuditEvent",
    "ModelAsset",
    "RegistrationRequest",
    "utc_now_iso",
]
