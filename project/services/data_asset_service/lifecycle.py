from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LifecycleKind(str, Enum):
    KNOWLEDGE = "knowledge"
    SIMULATION_MODEL = "simulation_model"
    DATASET = "dataset"
    INDEX_GENERATION = "index_generation"
    SIMULATION_EVIDENCE = "simulation_evidence"
    OPERATIONS_RUNTIME = "operations_runtime"


@dataclass(frozen=True)
class LifecycleDefinition:
    kind: LifecycleKind
    states: tuple[str, ...]
    owner_seam: str
    orthogonal_attributes: tuple[str, ...]
    invariants: tuple[str, ...]
    d2_mutation_authorized: bool = False


_LIFECYCLES = {
    LifecycleKind.KNOWLEDGE: LifecycleDefinition(
        LifecycleKind.KNOWLEDGE,
        ("uploaded", "staged", "validated", "committed", "corrected", "revised", "withdrawn", "archived"),
        "existing Admin Staging Lifecycle + Knowledge Correction + canonical ingestion writer/readback",
        ("included/excluded", "effective edit revision", "index stale status"),
        ("withdrawal cannot delete committed knowledge", "correction history remains immutable"),
    ),
    LifecycleKind.SIMULATION_MODEL: LifecycleDefinition(
        LifecycleKind.SIMULATION_MODEL,
        ("draft", "validated", "compiled", "pending_approval", "approved", "enabled", "disabled", "rejected", "deleted", "tombstoned"),
        "existing Generated Model Lifecycle and uploaded model-assets lifecycle",
        ("origin: llm_generated/admin_uploaded", "retention: ephemeral/resident", "revision"),
        ("enabled model must be disabled before deletion", "delete keeps tombstone", "Model IR revisions are append-only"),
    ),
    LifecycleKind.DATASET: LifecycleDefinition(
        LifecycleKind.DATASET,
        ("draft", "validated", "frozen", "deprecated", "archived"),
        "D2 policy only; persistence begins in D3",
        ("purpose", "training eligibility", "version", "parent lineage"),
        ("frozen versions cannot mutate in place", "curation creates a new identity/version"),
    ),
    LifecycleKind.INDEX_GENERATION: LifecycleDefinition(
        LifecycleKind.INDEX_GENERATION,
        ("building", "candidate", "validated", "ready_to_release", "active", "stale", "superseded", "failed", "blocked"),
        "existing copy-on-write candidate builder, validator and release gate",
        ("validation status", "release status", "active"),
        ("validated does not imply active", "ready_to_release does not imply released", "D2 cannot switch active index"),
    ),
    LifecycleKind.SIMULATION_EVIDENCE: LifecycleDefinition(
        LifecycleKind.SIMULATION_EVIDENCE,
        ("created", "validated", "archived"),
        "existing guarded runtime evidence writers; Case persistence begins in D4",
        ("execution type: real/mock", "verification status", "MATLAB version"),
        ("real execution does not imply human verification", "raw absolute artifact paths are not safe projections"),
    ),
    LifecycleKind.OPERATIONS_RUNTIME: LifecycleDefinition(
        LifecycleKind.OPERATIONS_RUNTIME,
        ("queued", "running", "succeeded", "failed", "cancelled", "archived"),
        "existing AdminJobStore/AdminAuditStore and runtime owners",
        ("append-only audit", "host-local job receipt", "runtime retention"),
        ("Job is not engineering evidence", "Audit is not knowledge", "Chat Agent cannot read Audit"),
    ),
}


def lifecycle_definition(kind: LifecycleKind | str) -> LifecycleDefinition:
    try:
        normalized = LifecycleKind(kind)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported lifecycle kind: {kind!r}") from exc
    return _LIFECYCLES[normalized]


def lifecycle_catalog() -> tuple[LifecycleDefinition, ...]:
    return tuple(_LIFECYCLES.values())


__all__ = ["LifecycleDefinition", "LifecycleKind", "lifecycle_catalog", "lifecycle_definition"]
