from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .contracts import AssetDescriptor, AssetRole, AssetType, ProvenanceStatus


class CompletenessStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CompletenessReport:
    status: CompletenessStatus
    missing_fields: tuple[str, ...]
    reasons: tuple[str, ...]


_HASH_REQUIRED = frozenset({
    AssetType.DOCUMENT,
    AssetType.CHUNK,
    AssetType.MODEL_REVISION,
    AssetType.MODEL_IR,
    AssetType.SIMULATION_EVIDENCE,
    AssetType.DATASET_VERSION,
    AssetType.EXPERIMENT_SNAPSHOT,
})


def assess_completeness(value: AssetDescriptor | Mapping[str, Any]) -> CompletenessReport:
    """Assess declared evidence without inventing missing provenance or identity."""

    if isinstance(value, Mapping):
        missing = tuple(key for key in ("asset_type", "asset_id") if not value.get(key))
        if missing:
            return CompletenessReport(CompletenessStatus.MISSING, missing, ("CANONICAL_IDENTITY_MISSING",))
        return CompletenessReport(
            CompletenessStatus.UNKNOWN,
            (),
            ("UNNORMALIZED_DESCRIPTOR_REQUIRES_VALIDATION",),
        )
    if not isinstance(value, AssetDescriptor):
        raise TypeError("completeness requires an AssetDescriptor or descriptor mapping")
    if value.role is AssetRole.UNKNOWN:
        return CompletenessReport(CompletenessStatus.UNKNOWN, (), ("ASSET_ROLE_UNKNOWN",))

    missing_fields: list[str] = []
    reasons: list[str] = []
    asset_type = value.asset_ref.asset_type
    if asset_type in _HASH_REQUIRED and not value.content_hash:
        missing_fields.append("content_hash")
        reasons.append("REQUIRED_HASH_MISSING")
    if asset_type is AssetType.DOCUMENT and value.provenance.source_asset_ref is None:
        missing_fields.append("provenance.source_asset_ref")
        reasons.append("SOURCE_ASSET_PROVENANCE_MISSING")
    if asset_type is AssetType.SIMULATION_EVIDENCE:
        for field_name in ("execution_type", "verification_status"):
            if not value.metadata.get(field_name):
                missing_fields.append(f"metadata.{field_name}")
                reasons.append("SIMULATION_EVIDENCE_METADATA_INCOMPLETE")

    declared = value.provenance.status
    if declared is ProvenanceStatus.MISSING:
        return CompletenessReport(
            CompletenessStatus.MISSING,
            tuple(dict.fromkeys(missing_fields or ["provenance"])),
            tuple(dict.fromkeys(reasons or ["PROVENANCE_MISSING"])),
        )
    if declared is ProvenanceStatus.UNKNOWN:
        return CompletenessReport(
            CompletenessStatus.UNKNOWN,
            tuple(dict.fromkeys(missing_fields)),
            tuple(dict.fromkeys(reasons or ["PROVENANCE_UNKNOWN"])),
        )
    if declared is ProvenanceStatus.PARTIAL or missing_fields:
        return CompletenessReport(
            CompletenessStatus.PARTIAL,
            tuple(dict.fromkeys(missing_fields)),
            tuple(dict.fromkeys(reasons or ["PROVENANCE_DECLARED_PARTIAL"])),
        )
    return CompletenessReport(CompletenessStatus.COMPLETE, (), ())


__all__ = ["CompletenessReport", "CompletenessStatus", "assess_completeness"]
