from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .contracts import AssetRef, AssetType


class LineageRelation(str, Enum):
    SOURCED_FROM = "sourced_from"
    PARSED_FROM = "parsed_from"
    CORRECTED_FROM = "corrected_from"
    DERIVED_FROM = "derived_from"
    VALIDATED_BY = "validated_by"
    COMPILED_FROM = "compiled_from"
    EXECUTED_FROM = "executed_from"
    CHECKED_BY = "checked_by"
    CRITIQUED_BY = "critiqued_by"


@dataclass(frozen=True)
class LineageEdge:
    parent: AssetRef
    child: AssetRef
    relation: LineageRelation | str

    def __post_init__(self) -> None:
        if not isinstance(self.parent, AssetRef) or not isinstance(self.child, AssetRef):
            raise ValueError("lineage edges require AssetRef endpoints")
        try:
            object.__setattr__(self, "relation", LineageRelation(self.relation))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported lineage relation: {self.relation!r}") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "parent": self.parent.to_dict(),
            "child": self.child.to_dict(),
            "relation": self.relation.value,
        }


@dataclass(frozen=True)
class LineageDescriptor:
    asset_ref: AssetRef
    edges: tuple[LineageEdge, ...]
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError(f"unsupported lineage schema version: {self.schema_version!r}")
        if not isinstance(self.asset_ref, AssetRef) or any(not isinstance(edge, LineageEdge) for edge in self.edges):
            raise ValueError("lineage descriptor requires validated refs and edges")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "asset_ref": self.asset_ref.to_dict(),
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class SimulationCaseLineageReport:
    valid: bool
    missing_asset_types: tuple[AssetType, ...]


SIMULATION_CASE_REQUIRED_LINEAGE = (
    AssetType.MODEL_REVISION,
    AssetType.SIMULATION_EVIDENCE,
    AssetType.REFERENCE_RESULT,
    AssetType.CRITIC_RESULT,
)

KNOWLEDGE_LINEAGE = (
    AssetType.SOURCE_ASSET,
    AssetType.DOCUMENT,
    AssetType.RAW_PARSER_OUTPUT,
    AssetType.STAGED_CHUNK,
    AssetType.CHUNK,
    AssetType.KNOWLEDGE_UNIT,
    AssetType.EMBEDDING,
    AssetType.RETRIEVAL_INDEX_GENERATION,
)

SIMULATION_LINEAGE = (
    AssetType.MODEL_IR,
    AssetType.MODEL_REVISION,
    AssetType.VALIDATION_EVIDENCE,
    AssetType.COMPILED_ARTIFACT,
    AssetType.SIMULATION_EVIDENCE,
    AssetType.REFERENCE_RESULT,
    AssetType.CRITIC_RESULT,
    AssetType.SIMULATION_CASE,
)


def validate_simulation_case_lineage(refs: Iterable[AssetRef]) -> SimulationCaseLineageReport:
    normalized = tuple(refs)
    if any(not isinstance(ref, AssetRef) for ref in normalized):
        raise ValueError("simulation case lineage accepts AssetRef values only")
    present = {ref.asset_type for ref in normalized}
    missing = tuple(asset_type for asset_type in SIMULATION_CASE_REQUIRED_LINEAGE if asset_type not in present)
    return SimulationCaseLineageReport(valid=not missing, missing_asset_types=missing)


__all__ = [
    "KNOWLEDGE_LINEAGE",
    "LineageDescriptor",
    "LineageEdge",
    "LineageRelation",
    "SIMULATION_CASE_REQUIRED_LINEAGE",
    "SIMULATION_LINEAGE",
    "SimulationCaseLineageReport",
    "validate_simulation_case_lineage",
]
