from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import AssetRef, AssetType, ProvenanceStatus, validate_sha256


class IndexType(str, Enum):
    FAISS = "faiss"
    BM25 = "bm25"
    HYBRID = "hybrid"


class IndexValidationStatus(str, Enum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class IndexReleaseStatus(str, Enum):
    BUILDING = "building"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    READY_TO_RELEASE = "ready_to_release"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    BLOCKED = "blocked"


class DriftStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class IndexGenerationDescriptor:
    generation_id: str
    index_type: IndexType | str
    source_content_digest: str | None
    source_chunk_count: int | None
    artifact_count: int | None
    artifact_hash: str | None
    created_at: str | None
    validation_status: IndexValidationStatus | str
    release_status: IndexReleaseStatus | str
    active: bool
    provenance_status: ProvenanceStatus | str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        ref = AssetRef(AssetType.RETRIEVAL_INDEX_GENERATION, self.generation_id)
        object.__setattr__(self, "generation_id", str(ref.native_id))
        try:
            object.__setattr__(self, "index_type", IndexType(self.index_type))
            object.__setattr__(self, "validation_status", IndexValidationStatus(self.validation_status))
            object.__setattr__(self, "release_status", IndexReleaseStatus(self.release_status))
            object.__setattr__(self, "provenance_status", ProvenanceStatus(self.provenance_status))
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported index generation contract value") from exc
        if self.schema_version != "1.0":
            raise ValueError(f"unsupported index generation schema version: {self.schema_version!r}")
        if self.source_content_digest is not None:
            object.__setattr__(self, "source_content_digest", validate_sha256(self.source_content_digest))
        if self.artifact_hash is not None:
            object.__setattr__(self, "artifact_hash", validate_sha256(self.artifact_hash))
        for field_name in ("source_chunk_count", "artifact_count"):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or int(value) < 0):
                raise ValueError(f"{field_name} must be a non-negative integer")
            if value is not None:
                object.__setattr__(self, field_name, int(value))

    @property
    def released(self) -> bool:
        return bool(self.active and self.release_status is IndexReleaseStatus.ACTIVE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generation_id": self.generation_id,
            "index_type": self.index_type.value,
            "source_content_digest": self.source_content_digest,
            "source_chunk_count": self.source_chunk_count,
            "artifact_count": self.artifact_count,
            "artifact_hash": self.artifact_hash,
            "created_at": self.created_at,
            "validation_status": self.validation_status.value,
            "release_status": self.release_status.value,
            "active": bool(self.active),
            "released": self.released,
            "provenance_status": self.provenance_status.value,
        }


@dataclass(frozen=True)
class DriftReport:
    status: DriftStatus
    reasons: tuple[str, ...]
    generation_id: str
    expected_source_chunk_count: int | None
    current_source_chunk_count: int | None
    expected_source_content_digest: str | None
    current_source_content_digest: str | None


def assess_index_drift(
    generation: IndexGenerationDescriptor,
    *,
    current_source_chunk_count: int | None,
    current_source_content_digest: str | None,
) -> DriftReport:
    if not isinstance(generation, IndexGenerationDescriptor):
        raise TypeError("index drift requires an IndexGenerationDescriptor")
    current_digest = (
        validate_sha256(current_source_content_digest) if current_source_content_digest is not None else None
    )
    missing_metadata = (
        generation.source_chunk_count is None
        or generation.source_content_digest is None
        or current_source_chunk_count is None
        or current_digest is None
    )
    if missing_metadata:
        return DriftReport(
            DriftStatus.UNKNOWN,
            ("INDEX_GENERATION_METADATA_INCOMPLETE",),
            generation.generation_id,
            generation.source_chunk_count,
            current_source_chunk_count,
            generation.source_content_digest,
            current_digest,
        )
    reasons: list[str] = []
    if int(generation.source_chunk_count) != int(current_source_chunk_count):
        reasons.append("SOURCE_CHUNK_COUNT_DRIFT")
    if generation.source_content_digest != current_digest:
        reasons.append("SOURCE_CONTENT_DIGEST_DRIFT")
    return DriftReport(
        DriftStatus.STALE if reasons else DriftStatus.CURRENT,
        tuple(reasons),
        generation.generation_id,
        generation.source_chunk_count,
        int(current_source_chunk_count),
        generation.source_content_digest,
        current_digest,
    )


__all__ = [
    "DriftReport",
    "DriftStatus",
    "IndexGenerationDescriptor",
    "IndexReleaseStatus",
    "IndexType",
    "IndexValidationStatus",
    "assess_index_drift",
]
