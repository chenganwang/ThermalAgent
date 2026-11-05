from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .contracts import TrainingEligibility


class DatasetPurpose(str, Enum):
    TRAINING = "training"
    VALIDATION = "validation"
    EVALUATION = "evaluation"
    SYNTHETIC = "synthetic"


class DatasetUsage(str, Enum):
    REGRESSION = "regression"
    BDD = "bdd"
    HOLDOUT = "holdout"
    BENCHMARK = "benchmark"
    CURATED_TRAINING = "curated_training"


@dataclass(frozen=True)
class DatasetPolicyDecision:
    purpose: DatasetPurpose
    frozen: bool
    training_eligibility: TrainingEligibility
    training_allowed: bool
    mutation_allowed: bool
    requires_new_identity_version: bool
    reasons: tuple[str, ...]


class DatasetPolicy:
    """Pure dataset-use policy. It performs no registry or filesystem I/O."""

    _NON_TRAINING_USAGES = frozenset({
        DatasetUsage.REGRESSION,
        DatasetUsage.BDD,
        DatasetUsage.HOLDOUT,
        DatasetUsage.BENCHMARK,
    })

    def evaluate(
        self,
        *,
        purpose: DatasetPurpose | str,
        frozen: bool,
        requested_training_eligibility: TrainingEligibility | str = TrainingEligibility.UNKNOWN,
        usages: Iterable[DatasetUsage | str] = (),
        dataset_id: str | None = None,
        name: str | None = None,
    ) -> DatasetPolicyDecision:
        del dataset_id, name  # identity and display labels never weaken policy
        try:
            normalized_purpose = DatasetPurpose(purpose)
            requested = TrainingEligibility(requested_training_eligibility)
            normalized_usages = frozenset(DatasetUsage(item) for item in usages)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported dataset policy value") from exc

        reasons: list[str] = []
        eligibility = requested
        if normalized_purpose in {DatasetPurpose.EVALUATION, DatasetPurpose.VALIDATION}:
            eligibility = TrainingEligibility.FORBIDDEN
            reasons.append("PURPOSE_RESERVED_FROM_TRAINING")
        if normalized_usages.intersection(self._NON_TRAINING_USAGES):
            eligibility = TrainingEligibility.FORBIDDEN
            reasons.append("USAGE_RESERVED_FROM_TRAINING")
        if normalized_purpose is DatasetPurpose.SYNTHETIC and eligibility is not TrainingEligibility.FORBIDDEN:
            eligibility = TrainingEligibility.REQUIRES_CURATION
            reasons.append("SYNTHETIC_REQUIRES_CURATION")
        if normalized_purpose is DatasetPurpose.TRAINING and requested is TrainingEligibility.ALLOWED:
            eligibility = TrainingEligibility.ALLOWED
        if eligibility is TrainingEligibility.UNKNOWN:
            reasons.append("UNKNOWN_ELIGIBILITY_DENIED")

        training_allowed = (
            normalized_purpose is DatasetPurpose.TRAINING
            and eligibility is TrainingEligibility.ALLOWED
            and not normalized_usages.intersection(self._NON_TRAINING_USAGES)
        )
        if not training_allowed and not reasons:
            reasons.append("TRAINING_NOT_EXPLICITLY_ALLOWED")
        mutation_allowed = not bool(frozen)
        if frozen:
            reasons.append("FROZEN_IMMUTABLE")
        requires_new_identity_version = eligibility is TrainingEligibility.REQUIRES_CURATION or bool(frozen)
        return DatasetPolicyDecision(
            purpose=normalized_purpose,
            frozen=bool(frozen),
            training_eligibility=eligibility,
            training_allowed=training_allowed,
            mutation_allowed=mutation_allowed,
            requires_new_identity_version=requires_new_identity_version,
            reasons=tuple(dict.fromkeys(reasons)),
        )


__all__ = ["DatasetPolicy", "DatasetPolicyDecision", "DatasetPurpose", "DatasetUsage"]
