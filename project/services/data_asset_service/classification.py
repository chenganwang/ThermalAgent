from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    AssetDomain,
    AssetRole,
    AssetType,
    Immutability,
    TrainingEligibility,
)


@dataclass(frozen=True)
class AssetClassification:
    domain: AssetDomain
    role: AssetRole
    immutability: Immutability
    delete_allowed: bool
    training_eligibility: TrainingEligibility


_TYPE_CLASSIFICATION: dict[AssetType, tuple[AssetDomain, AssetRole, Immutability]] = {
    AssetType.SOURCE_ASSET: (AssetDomain.KNOWLEDGE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.DOCUMENT: (AssetDomain.KNOWLEDGE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.DOCUMENT_SECTION: (AssetDomain.KNOWLEDGE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.RAW_PARSER_OUTPUT: (AssetDomain.KNOWLEDGE, AssetRole.RUNTIME, Immutability.MUTABLE),
    AssetType.STAGED_CHUNK: (AssetDomain.KNOWLEDGE, AssetRole.RUNTIME, Immutability.MUTABLE),
    AssetType.CHUNK: (AssetDomain.KNOWLEDGE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.KNOWLEDGE_UNIT: (AssetDomain.KNOWLEDGE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.EMBEDDING: (AssetDomain.KNOWLEDGE, AssetRole.DERIVED, Immutability.MUTABLE),
    AssetType.OCR_CACHE: (AssetDomain.KNOWLEDGE, AssetRole.DERIVED, Immutability.MUTABLE),
    AssetType.RETRIEVAL_INDEX_GENERATION: (AssetDomain.KNOWLEDGE, AssetRole.DERIVED, Immutability.VERSIONED),
    AssetType.SIMULATION_MODEL: (AssetDomain.SIMULATION_MODEL, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.MODEL_REVISION: (AssetDomain.SIMULATION_MODEL, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.MODEL_IR: (AssetDomain.SIMULATION_MODEL, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.COMPONENT_REGISTRY: (AssetDomain.SIMULATION_MODEL, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.VALIDATION_EVIDENCE: (AssetDomain.SIMULATION_MODEL, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.COMPILED_ARTIFACT: (AssetDomain.SIMULATION_MODEL, AssetRole.DERIVED, Immutability.MUTABLE),
    AssetType.SIMULATION_EVIDENCE: (AssetDomain.SIMULATION_EVIDENCE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.REFERENCE_RESULT: (AssetDomain.SIMULATION_EVIDENCE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.CRITIC_RESULT: (AssetDomain.SIMULATION_EVIDENCE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.SIMULATION_CASE: (AssetDomain.SIMULATION_EVIDENCE, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.JOB: (AssetDomain.OPERATIONS, AssetRole.RUNTIME, Immutability.MUTABLE),
    AssetType.AUDIT_EVENT: (AssetDomain.OPERATIONS, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.DATASET: (AssetDomain.DATASET, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.DATASET_VERSION: (AssetDomain.DATASET, AssetRole.CANONICAL, Immutability.VERSIONED),
    AssetType.EXPERIMENT_SNAPSHOT: (AssetDomain.DATASET, AssetRole.CANONICAL, Immutability.FROZEN),
}


def classify_asset_type(
    asset_type: AssetType | str,
    *,
    observed_role: AssetRole | str | None = None,
    frozen: bool = False,
) -> AssetClassification:
    """Return type-driven governance defaults; observation may only make them safer."""

    try:
        normalized_type = AssetType(asset_type)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported asset type: {asset_type!r}") from exc
    domain, default_role, default_immutability = _TYPE_CLASSIFICATION[normalized_type]
    try:
        role = AssetRole(observed_role) if observed_role is not None else default_role
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported observed asset role: {observed_role!r}") from exc
    immutability = Immutability.FROZEN if frozen else default_immutability
    eligibility = TrainingEligibility.UNKNOWN if domain is AssetDomain.DATASET else TrainingEligibility.FORBIDDEN
    if role is AssetRole.UNKNOWN:
        eligibility = TrainingEligibility.FORBIDDEN
    return AssetClassification(
        domain=domain,
        role=role,
        immutability=immutability,
        delete_allowed=False,
        training_eligibility=eligibility,
    )


def registered_asset_types() -> tuple[AssetType, ...]:
    return tuple(_TYPE_CLASSIFICATION)


__all__ = ["AssetClassification", "classify_asset_type", "registered_asset_types"]
