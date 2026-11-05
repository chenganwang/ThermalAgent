from __future__ import annotations

from dataclasses import dataclass

from .classification import classify_asset_type, registered_asset_types
from .contracts import AssetDomain, AssetRole, AssetType, Immutability, TrainingEligibility


@dataclass(frozen=True)
class AssetTypeDefinition:
    asset_type: AssetType
    domain: AssetDomain
    role: AssetRole
    immutability: Immutability
    native_identity: str
    canonical_store: str
    owner: str
    readers: tuple[str, ...]
    writer: str
    delete_authority: str
    derived_artifacts: tuple[str, ...]
    llm_access: str
    admin_access: str
    training_eligibility: TrainingEligibility
    retention: str
    version_contract: str
    hash_contract: str
    provenance_requirements: tuple[str, ...]
    completeness_rules: tuple[str, ...]
    lifecycle: str


_NATIVE_IDENTITY = {
    AssetType.SOURCE_ASSET: "existing source_asset_id",
    AssetType.DOCUMENT: "existing document_id",
    AssetType.DOCUMENT_SECTION: "existing section row id",
    AssetType.RAW_PARSER_OUTPUT: "opaque staging_id + parser output identity",
    AssetType.STAGED_CHUNK: "opaque staging_id + staged chunk identity",
    AssetType.CHUNK: "existing chunk_id",
    AssetType.KNOWLEDGE_UNIT: "existing knowledge_unit_id/unit_code",
    AssetType.EMBEDDING: "existing chunk_id + embedding build identity",
    AssetType.OCR_CACHE: "source digest + page identity",
    AssetType.RETRIEVAL_INDEX_GENERATION: "generation_id",
    AssetType.SIMULATION_MODEL: "existing model_id/generation_id",
    AssetType.MODEL_REVISION: "model_id + existing revision",
    AssetType.MODEL_IR: "model revision ref",
    AssetType.COMPONENT_REGISTRY: "registry_version",
    AssetType.VALIDATION_EVIDENCE: "parent revision + validation identity",
    AssetType.COMPILED_ARTIFACT: "opaque artifact_id",
    AssetType.SIMULATION_EVIDENCE: "existing evidence_id",
    AssetType.REFERENCE_RESULT: "parent execution + reference identity",
    AssetType.CRITIC_RESULT: "parent execution + critic identity",
    AssetType.SIMULATION_CASE: "future simulation_case_id",
    AssetType.JOB: "existing job_id",
    AssetType.AUDIT_EVENT: "existing audit event_id",
    AssetType.DATASET: "future dataset_id",
    AssetType.DATASET_VERSION: "future dataset_id + version",
    AssetType.EXPERIMENT_SNAPSHOT: "future experiment_snapshot_id",
}

_STORE = {
    AssetType.SOURCE_ASSET: "mysql.source_assets",
    AssetType.DOCUMENT: "mysql.documents",
    AssetType.DOCUMENT_SECTION: "mysql.document_sections",
    AssetType.RAW_PARSER_OUTPUT: "existing admin knowledge staging store",
    AssetType.STAGED_CHUNK: "existing admin knowledge staging store",
    AssetType.CHUNK: "mysql.chunks",
    AssetType.KNOWLEDGE_UNIT: "mysql.knowledge_units",
    AssetType.EMBEDDING: "mysql.embeddings",
    AssetType.OCR_CACHE: "data/ocr_cache",
    AssetType.RETRIEVAL_INDEX_GENERATION: "indexes + runtime/index_upgrade",
    AssetType.SIMULATION_MODEL: "existing catalog and generated-model repositories",
    AssetType.MODEL_REVISION: "runtime/generated_models/records",
    AssetType.MODEL_IR: "embedded in generated-model revision",
    AssetType.COMPONENT_REGISTRY: "code-defined reviewed registry",
    AssetType.VALIDATION_EVIDENCE: "embedded revision/compiler evidence",
    AssetType.COMPILED_ARTIFACT: "runtime/generated_models/staging",
    AssetType.SIMULATION_EVIDENCE: "runtime/simulation/evidence",
    AssetType.REFERENCE_RESULT: "existing execution/reference result envelopes",
    AssetType.CRITIC_RESULT: "existing critic/Admin operation receipts",
    AssetType.SIMULATION_CASE: "not implemented; D4 contract placeholder",
    AssetType.JOB: "runtime/admin_console/jobs",
    AssetType.AUDIT_EVENT: "runtime/admin_console/audit",
    AssetType.DATASET: "existing repository dataset files; registry not implemented",
    AssetType.DATASET_VERSION: "existing repository dataset files; registry not implemented",
    AssetType.EXPERIMENT_SNAPSHOT: "not implemented; D5 contract placeholder",
}

_OWNER = {
    AssetType.SOURCE_ASSET: "ingestion_service",
    AssetType.DOCUMENT: "ingestion_service",
    AssetType.DOCUMENT_SECTION: "ingestion_service",
    AssetType.RAW_PARSER_OUTPUT: "admin_ingestion_workflow",
    AssetType.STAGED_CHUNK: "admin_ingestion_workflow",
    AssetType.CHUNK: "ingestion_service",
    AssetType.KNOWLEDGE_UNIT: "ingest_knowledge_workflow",
    AssetType.EMBEDDING: "retrieval_indexing",
    AssetType.OCR_CACHE: "ingestion_ocr",
    AssetType.RETRIEVAL_INDEX_GENERATION: "retrieval_indexing",
    AssetType.SIMULATION_MODEL: "simulation_service",
    AssetType.MODEL_REVISION: "generated_model_lifecycle",
    AssetType.MODEL_IR: "generated_model_lifecycle",
    AssetType.COMPONENT_REGISTRY: "simulation_modeling",
    AssetType.VALIDATION_EVIDENCE: "simulation_modeling",
    AssetType.COMPILED_ARTIFACT: "simulation_compiler",
    AssetType.SIMULATION_EVIDENCE: "simulation_runtime",
    AssetType.REFERENCE_RESULT: "reference_checker",
    AssetType.CRITIC_RESULT: "result_critic",
    AssetType.SIMULATION_CASE: "unassigned_until_D4",
    AssetType.JOB: "admin_service",
    AssetType.AUDIT_EVENT: "admin_service",
    AssetType.DATASET: "evaluation_owners_until_D3",
    AssetType.DATASET_VERSION: "evaluation_owners_until_D3",
    AssetType.EXPERIMENT_SNAPSHOT: "unassigned_until_D5",
}

_WRITER = {
    AssetType.SOURCE_ASSET: "canonical ingestion writer",
    AssetType.DOCUMENT: "canonical ingestion writer",
    AssetType.DOCUMENT_SECTION: "canonical ingestion writer",
    AssetType.RAW_PARSER_OUTPUT: "existing parser/staging workflow",
    AssetType.STAGED_CHUNK: "existing parser/edit/exclude workflow",
    AssetType.CHUNK: "canonical ingestion writer/readback",
    AssetType.KNOWLEDGE_UNIT: "controlled KU writer",
    AssetType.EMBEDDING: "existing embedding writer",
    AssetType.OCR_CACHE: "existing OCR cache writer",
    AssetType.RETRIEVAL_INDEX_GENERATION: "copy-on-write index builder",
    AssetType.SIMULATION_MODEL: "existing catalog/generated-model lifecycle",
    AssetType.MODEL_REVISION: "generated-model lifecycle",
    AssetType.MODEL_IR: "generated-model lifecycle engineering revision",
    AssetType.COMPONENT_REGISTRY: "reviewed source change",
    AssetType.VALIDATION_EVIDENCE: "deterministic validator/compiler",
    AssetType.COMPILED_ARTIFACT: "controlled compiler artifact store",
    AssetType.SIMULATION_EVIDENCE: "guarded simulation runtime",
    AssetType.REFERENCE_RESULT: "reference checker",
    AssetType.CRITIC_RESULT: "result critic workflow",
    AssetType.SIMULATION_CASE: "none in D2",
    AssetType.JOB: "AdminJobStore",
    AssetType.AUDIT_EVENT: "AdminAuditStore append",
    AssetType.DATASET: "none in D2",
    AssetType.DATASET_VERSION: "none in D2",
    AssetType.EXPERIMENT_SNAPSHOT: "none in D2",
}


def asset_type_definition(asset_type: AssetType | str) -> AssetTypeDefinition:
    try:
        normalized = AssetType(asset_type)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported asset type: {asset_type!r}") from exc
    classification = classify_asset_type(normalized)
    dataset = classification.domain is AssetDomain.DATASET
    return AssetTypeDefinition(
        asset_type=normalized,
        domain=classification.domain,
        role=classification.role,
        immutability=classification.immutability,
        native_identity=_NATIVE_IDENTITY[normalized],
        canonical_store=_STORE[normalized],
        owner=_OWNER[normalized],
        readers=("governed services through access policy",),
        writer=_WRITER[normalized],
        delete_authority="existing owner lifecycle only; none for unknown or D2 placeholders",
        derived_artifacts=("asset-type-specific rebuildable projections",),
        llm_access="deny by default; LLM_SAFE only when access policy grants",
        admin_access="ADMIN_SAFE when access policy grants",
        training_eligibility=TrainingEligibility.UNKNOWN if dataset else TrainingEligibility.FORBIDDEN,
        retention="existing owner lifecycle; unknown retains pending review",
        version_contract="native version/revision preserved; no ID migration",
        hash_contract="SHA-256 when available; missing/unavailable is explicit",
        provenance_requirements=("origin", "parent/source refs when available", "no fabricated locator"),
        completeness_rules=("complete/partial/missing/unknown",),
        lifecycle="reuse existing owner lifecycle; D2 adds no persistence state machine",
    )


def asset_type_catalog() -> tuple[AssetTypeDefinition, ...]:
    return tuple(asset_type_definition(asset_type) for asset_type in registered_asset_types())


__all__ = ["AssetTypeDefinition", "asset_type_catalog", "asset_type_definition"]
