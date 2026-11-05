from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .contracts import AssetDescriptor, AssetType
from .dataset_policy import DatasetPolicy
from .projection import ProjectionLevel


class Consumer(str, Enum):
    CHAT_AGENT = "chat_agent"
    RETRIEVAL_SERVICE = "retrieval_service"
    PLANNER = "planner"
    MODEL_SYNTHESIZER = "model_synthesizer"
    RESULT_CRITIC = "result_critic"
    SIMULATION_RUNTIME = "simulation_runtime"
    INGESTION_SERVICE = "ingestion_service"
    ADMIN_BACKEND = "admin_backend"
    TRAINING_PIPELINE = "training_pipeline"
    EVALUATION_PIPELINE = "evaluation_pipeline"


class AssetAction(str, Enum):
    READ = "read"
    WRITE = "write"
    MUTATE = "mutate"
    DELETE = "delete"
    TRAIN = "train"


class AccessPermission(str, Enum):
    NONE = "none"
    METADATA = "metadata"
    SAFE_CONTENT = "safe_content"
    FULL_INTERNAL = "full_internal"
    WRITE = "write"


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    permission: AccessPermission
    projection: ProjectionLevel | None
    reason: str


class AccessDeniedError(PermissionError):
    def __init__(self, decision: AccessDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


def _grant(
    matrix: dict[tuple[Consumer, AssetType], AccessPermission],
    consumer: Consumer,
    asset_types: Iterable[AssetType],
    permission: AccessPermission,
) -> None:
    for asset_type in asset_types:
        matrix[(consumer, asset_type)] = permission


def _build_matrix() -> dict[tuple[Consumer, AssetType], AccessPermission]:
    matrix: dict[tuple[Consumer, AssetType], AccessPermission] = {}
    knowledge = (
        AssetType.SOURCE_ASSET,
        AssetType.DOCUMENT,
        AssetType.CHUNK,
        AssetType.KNOWLEDGE_UNIT,
    )
    _grant(matrix, Consumer.CHAT_AGENT, knowledge, AccessPermission.SAFE_CONTENT)
    _grant(matrix, Consumer.CHAT_AGENT, (AssetType.SIMULATION_MODEL,), AccessPermission.METADATA)
    _grant(matrix, Consumer.CHAT_AGENT, (AssetType.SIMULATION_EVIDENCE,), AccessPermission.METADATA)

    _grant(matrix, Consumer.RETRIEVAL_SERVICE, knowledge, AccessPermission.SAFE_CONTENT)
    _grant(
        matrix,
        Consumer.RETRIEVAL_SERVICE,
        (AssetType.EMBEDDING, AssetType.RETRIEVAL_INDEX_GENERATION),
        AccessPermission.FULL_INTERNAL,
    )

    _grant(
        matrix,
        Consumer.PLANNER,
        (AssetType.SIMULATION_MODEL, AssetType.MODEL_REVISION),
        AccessPermission.METADATA,
    )
    _grant(
        matrix,
        Consumer.MODEL_SYNTHESIZER,
        (AssetType.SIMULATION_MODEL, AssetType.COMPONENT_REGISTRY, AssetType.MODEL_IR),
        AccessPermission.SAFE_CONTENT,
    )
    _grant(
        matrix,
        Consumer.RESULT_CRITIC,
        (AssetType.SIMULATION_EVIDENCE, AssetType.REFERENCE_RESULT, AssetType.MODEL_REVISION),
        AccessPermission.FULL_INTERNAL,
    )
    _grant(matrix, Consumer.RESULT_CRITIC, (AssetType.CRITIC_RESULT,), AccessPermission.WRITE)

    _grant(
        matrix,
        Consumer.SIMULATION_RUNTIME,
        (
            AssetType.SIMULATION_MODEL,
            AssetType.MODEL_REVISION,
            AssetType.MODEL_IR,
            AssetType.COMPONENT_REGISTRY,
            AssetType.COMPILED_ARTIFACT,
            AssetType.VALIDATION_EVIDENCE,
        ),
        AccessPermission.FULL_INTERNAL,
    )
    _grant(matrix, Consumer.SIMULATION_RUNTIME, (AssetType.SIMULATION_EVIDENCE,), AccessPermission.WRITE)

    _grant(
        matrix,
        Consumer.INGESTION_SERVICE,
        (
            AssetType.SOURCE_ASSET,
            AssetType.DOCUMENT,
            AssetType.DOCUMENT_SECTION,
            AssetType.RAW_PARSER_OUTPUT,
            AssetType.STAGED_CHUNK,
            AssetType.CHUNK,
            AssetType.KNOWLEDGE_UNIT,
        ),
        AccessPermission.WRITE,
    )

    _grant(matrix, Consumer.ADMIN_BACKEND, tuple(AssetType), AccessPermission.METADATA)
    _grant(
        matrix,
        Consumer.ADMIN_BACKEND,
        (
            AssetType.SOURCE_ASSET,
            AssetType.DOCUMENT,
            AssetType.CHUNK,
            AssetType.KNOWLEDGE_UNIT,
            AssetType.RETRIEVAL_INDEX_GENERATION,
            AssetType.SIMULATION_MODEL,
            AssetType.MODEL_REVISION,
            AssetType.MODEL_IR,
            AssetType.COMPILED_ARTIFACT,
            AssetType.SIMULATION_EVIDENCE,
            AssetType.JOB,
            AssetType.AUDIT_EVENT,
            AssetType.DATASET,
            AssetType.DATASET_VERSION,
            AssetType.EXPERIMENT_SNAPSHOT,
        ),
        AccessPermission.SAFE_CONTENT,
    )

    _grant(
        matrix,
        Consumer.TRAINING_PIPELINE,
        (AssetType.DATASET, AssetType.DATASET_VERSION),
        AccessPermission.SAFE_CONTENT,
    )
    _grant(
        matrix,
        Consumer.EVALUATION_PIPELINE,
        (AssetType.DATASET, AssetType.DATASET_VERSION, AssetType.EXPERIMENT_SNAPSHOT),
        AccessPermission.SAFE_CONTENT,
    )
    return matrix


_ACCESS_MATRIX = _build_matrix()


class AccessPolicy:
    """Deny-by-default policy over consumer, asset type, action and projection."""

    def decide(
        self,
        consumer: Consumer | str,
        asset_type: AssetType | str,
        action: AssetAction | str,
        projection: ProjectionLevel | str,
        *,
        descriptor: AssetDescriptor | None = None,
    ) -> AccessDecision:
        try:
            normalized_consumer = Consumer(consumer)
            normalized_type = AssetType(asset_type)
            normalized_action = AssetAction(action)
            normalized_projection = ProjectionLevel(projection)
        except (TypeError, ValueError):
            return AccessDecision(False, AccessPermission.NONE, None, "ACCESS_DENIED_UNKNOWN_CONTRACT_VALUE")

        permission = _ACCESS_MATRIX.get((normalized_consumer, normalized_type), AccessPermission.NONE)
        if permission is AccessPermission.NONE:
            return AccessDecision(False, permission, normalized_projection, "ACCESS_DENIED_BY_POLICY")
        if normalized_action is AssetAction.DELETE:
            return AccessDecision(False, permission, normalized_projection, "ACCESS_DELETE_NOT_AUTHORIZED_D2")
        if normalized_action in {AssetAction.WRITE, AssetAction.MUTATE} and permission is not AccessPermission.WRITE:
            return AccessDecision(False, permission, normalized_projection, "ACCESS_WRITE_NOT_AUTHORIZED")
        if normalized_projection is ProjectionLevel.ADMIN_SAFE and normalized_consumer is not Consumer.ADMIN_BACKEND:
            return AccessDecision(False, permission, normalized_projection, "ACCESS_ADMIN_PROJECTION_FORBIDDEN")
        if normalized_projection is ProjectionLevel.INTERNAL_SERVICE and permission not in {
            AccessPermission.FULL_INTERNAL,
            AccessPermission.WRITE,
        }:
            return AccessDecision(False, permission, normalized_projection, "ACCESS_INTERNAL_PROJECTION_FORBIDDEN")
        if normalized_action is AssetAction.TRAIN:
            allowed = False
            if (
                normalized_consumer is Consumer.TRAINING_PIPELINE
                and normalized_type in {AssetType.DATASET, AssetType.DATASET_VERSION}
                and descriptor is not None
            ):
                try:
                    dataset_decision = DatasetPolicy().evaluate(
                        purpose=str(descriptor.metadata.get("purpose") or ""),
                        frozen=bool(descriptor.to_dict()["frozen"]),
                        requested_training_eligibility=descriptor.training_eligibility,
                        usages=tuple(descriptor.metadata.get("usages") or ()),
                    )
                    allowed = dataset_decision.training_allowed
                except ValueError:
                    allowed = False
            return AccessDecision(
                allowed,
                permission,
                normalized_projection,
                "ACCESS_ALLOWED" if allowed else "DATASET_TRAINING_FORBIDDEN",
            )
        if normalized_action in {AssetAction.WRITE, AssetAction.MUTATE}:
            return AccessDecision(True, permission, normalized_projection, "ACCESS_ALLOWED")
        if normalized_action is AssetAction.READ:
            return AccessDecision(True, permission, normalized_projection, "ACCESS_ALLOWED")
        return AccessDecision(False, permission, normalized_projection, "ACCESS_DENIED_BY_POLICY")

    def authorize(self, *args, **kwargs) -> AccessDecision:
        decision = self.decide(*args, **kwargs)
        if not decision.allowed:
            raise AccessDeniedError(decision)
        return decision


def access_matrix() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "consumer": consumer.value,
            "asset_type": asset_type.value,
            "permission": permission.value,
        }
        for (consumer, asset_type), permission in sorted(
            _ACCESS_MATRIX.items(), key=lambda item: (item[0][0].value, item[0][1].value)
        )
    )


__all__ = [
    "AccessDecision",
    "AccessDeniedError",
    "AccessPermission",
    "AccessPolicy",
    "AssetAction",
    "Consumer",
    "access_matrix",
]
