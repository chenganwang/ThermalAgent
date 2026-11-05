from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any, Mapping


SUPPORTED_DESCRIPTOR_SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_FILENAME_RE = re.compile(r"^[^/\\]+\.[A-Za-z0-9]{1,10}$")


class _ContractEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AssetDomain(_ContractEnum):
    KNOWLEDGE = "knowledge"
    SIMULATION_MODEL = "simulation_model"
    SIMULATION_EVIDENCE = "simulation_evidence"
    OPERATIONS = "operations"
    DATASET = "dataset"


class AssetRole(_ContractEnum):
    CANONICAL = "canonical"
    DERIVED = "derived"
    RUNTIME = "runtime"
    UNKNOWN = "unknown"


class Immutability(_ContractEnum):
    MUTABLE = "mutable"
    VERSIONED = "versioned"
    FROZEN = "frozen"


class ProvenanceStatus(_ContractEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


class HashStatus(_ContractEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


class TrainingEligibility(_ContractEnum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"
    REQUIRES_CURATION = "requires_curation"
    UNKNOWN = "unknown"


class AssetType(_ContractEnum):
    SOURCE_ASSET = "source_asset"
    DOCUMENT = "document"
    DOCUMENT_SECTION = "document_section"
    RAW_PARSER_OUTPUT = "raw_parser_output"
    STAGED_CHUNK = "staged_chunk"
    CHUNK = "chunk"
    KNOWLEDGE_UNIT = "knowledge_unit"
    EMBEDDING = "embedding"
    OCR_CACHE = "ocr_cache"
    RETRIEVAL_INDEX_GENERATION = "retrieval_index_generation"
    SIMULATION_MODEL = "simulation_model"
    MODEL_REVISION = "model_revision"
    MODEL_IR = "model_ir"
    COMPONENT_REGISTRY = "component_registry"
    VALIDATION_EVIDENCE = "validation_evidence"
    COMPILED_ARTIFACT = "compiled_artifact"
    SIMULATION_EVIDENCE = "simulation_evidence"
    REFERENCE_RESULT = "reference_result"
    CRITIC_RESULT = "critic_result"
    SIMULATION_CASE = "simulation_case"
    JOB = "job"
    AUDIT_EVENT = "audit_event"
    DATASET = "dataset"
    DATASET_VERSION = "dataset_version"
    EXPERIMENT_SNAPSHOT = "experiment_snapshot"


def _coerce_enum(enum_type: type[_ContractEnum], value: _ContractEnum | str, field_name: str) -> _ContractEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported {field_name}: {value!r}") from exc


def _validate_native_id(value: int | str) -> str:
    if isinstance(value, bool):
        raise ValueError("asset native identity cannot be boolean")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("asset native integer identity cannot be negative")
        return str(value)
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("asset native identity is required")
    if (
        PureWindowsPath(normalized).is_absolute()
        or PurePosixPath(normalized).is_absolute()
        or normalized.casefold().startswith("file:")
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError("absolute paths and filesystem locators cannot be asset identity")
    if _FILENAME_RE.fullmatch(normalized):
        raise ValueError("filename cannot be asset identity")
    return normalized


def validate_sha256(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError("content hash must be a 64-character SHA-256 hex digest")
    return normalized


@dataclass(frozen=True)
class AssetRef:
    asset_type: AssetType | str
    native_id: int | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_type", _coerce_enum(AssetType, self.asset_type, "asset type"))
        object.__setattr__(self, "native_id", _validate_native_id(self.native_id))

    def to_dict(self) -> dict[str, str]:
        return {"asset_type": self.asset_type.value, "asset_id": str(self.native_id)}


@dataclass(frozen=True)
class Provenance:
    status: ProvenanceStatus | str = ProvenanceStatus.UNKNOWN
    origin: str | None = None
    source_asset_ref: AssetRef | None = None
    parent_asset_ref: AssetRef | None = None
    parent_revision_ref: AssetRef | None = None
    generation_method: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    software_version: str | None = None
    schema_version: str | None = None
    content_hash: str | None = None
    source_locator: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _coerce_enum(ProvenanceStatus, self.status, "provenance status"))
        if self.content_hash is not None:
            object.__setattr__(self, "content_hash", validate_sha256(self.content_hash))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "origin": self.origin,
            "source_asset_ref": self.source_asset_ref.to_dict() if self.source_asset_ref else None,
            "parent_asset_ref": self.parent_asset_ref.to_dict() if self.parent_asset_ref else None,
            "parent_revision_ref": self.parent_revision_ref.to_dict() if self.parent_revision_ref else None,
            "generation_method": self.generation_method,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "software_version": self.software_version,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
            "source_locator": self.source_locator,
        }


@dataclass(frozen=True)
class AssetDescriptor:
    asset_ref: AssetRef
    domain: AssetDomain | str
    role: AssetRole | str
    schema_version: str = SUPPORTED_DESCRIPTOR_SCHEMA_VERSION
    version: str | None = None
    content_hash: str | None = None
    title: str | None = None
    summary: str | None = None
    origin: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    retention: str | None = None
    immutability: Immutability | str = Immutability.MUTABLE
    provenance: Provenance = field(default_factory=Provenance)
    training_eligibility: TrainingEligibility | str = TrainingEligibility.UNKNOWN
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.asset_ref, AssetRef):
            raise ValueError("asset_ref must be an AssetRef")
        object.__setattr__(self, "domain", _coerce_enum(AssetDomain, self.domain, "asset domain"))
        object.__setattr__(self, "role", _coerce_enum(AssetRole, self.role, "asset role"))
        object.__setattr__(self, "immutability", _coerce_enum(Immutability, self.immutability, "immutability"))
        object.__setattr__(
            self,
            "training_eligibility",
            _coerce_enum(TrainingEligibility, self.training_eligibility, "training eligibility"),
        )
        if str(self.schema_version) != SUPPORTED_DESCRIPTOR_SCHEMA_VERSION:
            raise ValueError(f"unsupported asset descriptor schema version: {self.schema_version!r}")
        if self.content_hash is not None:
            object.__setattr__(self, "content_hash", validate_sha256(self.content_hash))
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance contract")
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata or {})))

    @property
    def hash_status(self) -> HashStatus:
        return HashStatus.AVAILABLE if self.content_hash else HashStatus.MISSING

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.asset_ref.to_dict(),
            "domain": self.domain.value,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "version": self.version,
            "content_hash": self.content_hash,
            "hash_status": self.hash_status.value,
            "title": self.title,
            "summary": self.summary,
            "origin": self.origin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "retention": self.retention,
            "immutability": self.immutability.value,
            "frozen": self.immutability is Immutability.FROZEN,
            "provenance_status": self.provenance.status.value,
            "provenance": self.provenance.to_dict(),
            "training_eligibility": self.training_eligibility.value,
            "metadata": deepcopy(dict(self.metadata)),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))

    def descriptor_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


__all__ = [
    "AssetDescriptor",
    "AssetDomain",
    "AssetRef",
    "AssetRole",
    "AssetType",
    "HashStatus",
    "Immutability",
    "Provenance",
    "ProvenanceStatus",
    "SUPPORTED_DESCRIPTOR_SCHEMA_VERSION",
    "TrainingEligibility",
    "validate_sha256",
]
