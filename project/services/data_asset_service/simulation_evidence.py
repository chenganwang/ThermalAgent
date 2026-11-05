from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import (
    AssetDescriptor,
    AssetDomain,
    AssetRef,
    AssetRole,
    AssetType,
    Immutability,
    Provenance,
    ProvenanceStatus,
    TrainingEligibility,
)


class ExecutionType(str, Enum):
    REAL = "real"
    MOCK = "mock"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    HUMAN_VERIFIED = "human_verified"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SimulationEvidenceDescriptor:
    """Typed read-only projection for existing simulation execution evidence.

    A real execution is deliberately independent from verification: observing
    MATLAB execution never upgrades evidence to human-verified status.
    """

    evidence_id: int | str
    execution_type: ExecutionType | str
    verification_status: VerificationStatus | str
    matlab_version: str | None = None
    content_hash: str | None = None
    safe_artifact_ref: str | None = None
    internal_artifact_locator: str | None = None

    def __post_init__(self) -> None:
        try:
            execution_type = ExecutionType(self.execution_type)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported execution type: {self.execution_type!r}") from exc
        try:
            verification_status = VerificationStatus(self.verification_status)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported verification status: {self.verification_status!r}") from exc
        object.__setattr__(self, "execution_type", execution_type)
        object.__setattr__(self, "verification_status", verification_status)
        if self.safe_artifact_ref is not None:
            AssetRef(AssetType.COMPILED_ARTIFACT, self.safe_artifact_ref)

    @property
    def asset(self) -> AssetDescriptor:
        provenance_status = ProvenanceStatus.COMPLETE if self.content_hash else ProvenanceStatus.PARTIAL
        return AssetDescriptor(
            asset_ref=AssetRef(AssetType.SIMULATION_EVIDENCE, self.evidence_id),
            domain=AssetDomain.SIMULATION_EVIDENCE,
            role=AssetRole.CANONICAL,
            content_hash=self.content_hash,
            immutability=Immutability.VERSIONED,
            provenance=Provenance(
                status=provenance_status,
                origin="simulation_runtime",
                generation_method="simulation_execution_capture",
                software_version=self.matlab_version,
                content_hash=self.content_hash,
                source_locator=self.internal_artifact_locator,
            ),
            training_eligibility=TrainingEligibility.FORBIDDEN,
            metadata={
                "execution_type": self.execution_type.value,
                "verification_status": self.verification_status.value,
                "matlab_version": self.matlab_version,
                "artifact_resolver_key": self.safe_artifact_ref,
                "internal_artifact_locator": self.internal_artifact_locator,
            },
        )


__all__ = ["ExecutionType", "SimulationEvidenceDescriptor", "VerificationStatus"]
