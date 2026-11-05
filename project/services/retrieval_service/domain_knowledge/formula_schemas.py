from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .provenance import ProvenanceRecord


@dataclass(frozen=True)
class FormulaVariable:
    symbol: str
    name_zh: str
    unit: str
    description_zh: str = ""
    required: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FormulaVariable":
        return cls(
            symbol=str(raw.get("symbol") or ""),
            name_zh=str(raw.get("name_zh") or ""),
            unit=str(raw.get("unit") or ""),
            description_zh=str(raw.get("description_zh") or ""),
            required=bool(raw.get("required", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FormulaRecord:
    formula_id: str
    name_zh: str
    name_en: str
    category: str
    expression: str
    latex: str
    variables: tuple[FormulaVariable, ...]
    physical_meaning_zh: str
    assumptions_zh: tuple[str, ...]
    applicability_zh: tuple[str, ...]
    limitations_zh: tuple[str, ...]
    keywords: tuple[str, ...]
    aliases: tuple[str, ...]
    tool_id: str | None
    examples_zh: tuple[str, ...]
    engineering_notes_zh: tuple[str, ...]
    criteria_zh: tuple[str, ...]
    provenance: ProvenanceRecord

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FormulaRecord":
        return cls(
            formula_id=str(raw.get("formula_id") or ""),
            name_zh=str(raw.get("name_zh") or ""),
            name_en=str(raw.get("name_en") or ""),
            category=str(raw.get("category") or ""),
            expression=str(raw.get("expression") or ""),
            latex=str(raw.get("latex") or raw.get("expression") or ""),
            variables=tuple(FormulaVariable.from_dict(item) for item in raw.get("variables") or []),
            physical_meaning_zh=str(raw.get("physical_meaning_zh") or ""),
            assumptions_zh=_tuple_str(raw.get("assumptions_zh")),
            applicability_zh=_tuple_str(raw.get("applicability_zh")),
            limitations_zh=_tuple_str(raw.get("limitations_zh")),
            keywords=_tuple_str(raw.get("keywords")),
            aliases=_tuple_str(raw.get("aliases")),
            tool_id=_optional_str(raw.get("tool_id")),
            examples_zh=_tuple_str(raw.get("examples_zh")),
            engineering_notes_zh=_tuple_str(raw.get("engineering_notes_zh")),
            criteria_zh=_tuple_str(raw.get("criteria_zh")),
            provenance=ProvenanceRecord.from_dict(raw.get("provenance")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["variables"] = [item.to_dict() for item in self.variables]
        data["provenance"] = self.provenance.to_dict()
        return data


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _tuple_str(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if item not in (None, ""))


__all__ = ["FormulaRecord", "FormulaVariable"]
