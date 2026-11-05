from __future__ import annotations

import json
from pathlib import Path

from .schemas import CatalogConfigurationError, ScenarioDefinition


class ScenarioCatalog:
    def __init__(self, data_path: Path | None = None) -> None:
        path = data_path or Path(__file__).with_name("data") / "scenarios.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.catalog_version = str(raw.get("catalog_version") or "unknown")
        items = [ScenarioDefinition.from_dict(item) for item in raw.get("scenarios") or ()]
        self._items = _unique(items)
        for item in items:
            _validate_schema(item)

    def list(self, *, domain: str | None = None, status: str | None = None) -> list[ScenarioDefinition]:
        return [x for x in self._items.values() if (domain is None or x.domain == domain) and (status is None or x.status == status)]

    def get(self, scenario_id: str) -> ScenarioDefinition | None:
        return self._items.get(str(scenario_id))


def _unique(items: list[ScenarioDefinition]) -> dict[str, ScenarioDefinition]:
    result: dict[str, ScenarioDefinition] = {}
    for item in items:
        if item.scenario_id in result:
            raise CatalogConfigurationError(f"duplicate scenario_id: {item.scenario_id}")
        result[item.scenario_id] = item
    return result


def _validate_schema(item: ScenarioDefinition) -> None:
    for kind, fields in (("input", item.input_schema), ("output", item.output_schema)):
        names = [str(field.get("name") or "") for field in fields]
        if not all(names) or len(names) != len(set(names)):
            raise CatalogConfigurationError(f"invalid {kind}_schema for {item.scenario_id}")
        if any(not field.get("label_zh") or not field.get("type") for field in fields):
            raise CatalogConfigurationError(f"incomplete {kind}_schema for {item.scenario_id}")


__all__ = ["ScenarioCatalog"]
