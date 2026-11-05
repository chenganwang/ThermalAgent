from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .formula_schemas import FormulaRecord


DEFAULT_FORMULA_DATA = Path(__file__).resolve().parent / "data" / "formulas.json"


def _normalize(text: str | None) -> str:
    value = str(text or "").strip().lower()
    value = value.replace("·", "*").replace("×", "*").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", value)


class FormulaRegistry:
    def __init__(self, data_path: str | Path | None = None) -> None:
        self.data_path = Path(data_path) if data_path is not None else DEFAULT_FORMULA_DATA
        self._records = self._load(self.data_path)
        self._by_id = {item.formula_id: item for item in self._records}
        if len(self._by_id) != len(self._records):
            raise ValueError(f"duplicate formula_id in {self.data_path}")

    @staticmethod
    def _load(path: Path) -> list[FormulaRecord]:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get("formulas") if isinstance(data, dict) else data
        if not isinstance(records, list):
            raise ValueError(f"{path}: formulas must be a list")
        parsed = [FormulaRecord.from_dict(item) for item in records]
        missing = [item for item in parsed if not item.formula_id or not item.expression or not item.variables]
        if missing:
            labels = ", ".join(item.formula_id or "<missing-id>" for item in missing)
            raise ValueError(f"{path}: formula records missing required fields: {labels}")
        return parsed

    def list_formulas(self) -> list[FormulaRecord]:
        return list(self._records)

    def get_formula(self, formula_id: str) -> FormulaRecord | None:
        return self._by_id.get(str(formula_id or ""))

    def find_formula(self, query: str, *, task_type: str | None = None) -> FormulaRecord | None:
        text = _normalize(query)
        if not text:
            return None

        best: tuple[int, FormulaRecord] | None = None
        for record in self._records:
            score = self._score(record, text, task_type=task_type)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, record)
        return None if best is None else best[1]

    def validate(self) -> list[str]:
        errors: list[str] = []
        for record in self._records:
            label = record.formula_id
            if not record.name_zh and not record.name_en:
                errors.append(f"{label}: name is required")
            if not record.physical_meaning_zh:
                errors.append(f"{label}: physical_meaning_zh is required")
            if not record.assumptions_zh:
                errors.append(f"{label}: assumptions_zh is required")
            if not record.applicability_zh:
                errors.append(f"{label}: applicability_zh is required")
            if not record.limitations_zh:
                errors.append(f"{label}: limitations_zh is required")
        return errors

    @staticmethod
    def _score(record: FormulaRecord, text: str, *, task_type: str | None = None) -> int:
        score = 0
        haystacks = [
            record.formula_id,
            record.name_zh,
            record.name_en,
            record.expression,
            *record.aliases,
            *record.keywords,
        ]
        for raw in haystacks:
            term = _normalize(raw)
            if not term:
                continue
            if term in text:
                score += 8 if raw in record.aliases or raw in record.keywords else 5
            else:
                compact = term.replace(" ", "")
                if compact and compact in text.replace(" ", ""):
                    score += 3
        if (task_type or "").lower() == "formula":
            score += 2
        if any(token in text for token in ("公式", "physical meaning", "参数", "meaning", "definition", "定义")):
            score += 1
        return score


@lru_cache(maxsize=1)
def get_default_formula_registry() -> FormulaRegistry:
    return FormulaRegistry()


def load_formula_records(data_path: str | Path | None = None) -> list[dict[str, Any]]:
    return [record.to_dict() for record in FormulaRegistry(data_path).list_formulas()]


__all__ = ["DEFAULT_FORMULA_DATA", "FormulaRegistry", "get_default_formula_registry", "load_formula_records"]
