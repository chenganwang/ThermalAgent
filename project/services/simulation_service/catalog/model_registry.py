from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ..model_catalog import load_builtin_model_catalog
from .schemas import CatalogConfigurationError, ModelDefinition
from .input_contracts import ModelInputResult, normalize_model_inputs


EXECUTABLE_STATUSES = {"available"}
REGISTRATION_TYPES = {"built_in", "operator_registered", "user_uploaded_unvalidated"}


class ModelRegistry:
    def __init__(self, data_path: Path | None = None, runtime_data_path: Path | None = None) -> None:
        path = data_path or Path(__file__).with_name("data") / "models.json"
        raw = load_builtin_model_catalog(path)
        self.registry_version = str(raw.get("registry_version") or "unknown")
        records = list(raw.get("models") or ())
        runtime_records: list[dict[str, object]] = []
        runtime_path = runtime_data_path
        if data_path is None and runtime_path is None:
            configured = os.getenv("SIMULATION_MODEL_METADATA_DIR", "runtime/simulation/model_assets/metadata").strip()
            metadata_path = Path(configured)
            if not metadata_path.is_absolute():
                metadata_path = Path(__file__).resolve().parents[3] / metadata_path
            runtime_path = metadata_path.parent / "registered_models.json"
        if runtime_path is not None and runtime_path.exists():
            import json

            runtime_raw = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_records = [dict(item) for item in runtime_raw.get("models") or ()]
            for item in runtime_records:
                if item.get("registration_type") != "operator_registered":
                    raise CatalogConfigurationError("runtime models must be operator_registered")
                if item.get("status") not in {"unvalidated", "preparation_only", "blocked", "archived"}:
                    raise CatalogConfigurationError("runtime model is not execution-certified")
                if item.get("entrypoint_id") is not None:
                    raise CatalogConfigurationError("runtime model cannot declare an executable entrypoint")
            records.extend(runtime_records)
            runtime_version = str(runtime_raw.get("registry_version") or "runtime")
            self.registry_version = f"{self.registry_version}+{runtime_version}"
        items = [ModelDefinition.from_dict(item) for item in records]
        self._items: dict[str, ModelDefinition] = {}
        for item in items:
            if item.model_id in self._items:
                raise CatalogConfigurationError(f"duplicate model_id: {item.model_id}")
            if item.registration_type not in REGISTRATION_TYPES:
                raise CatalogConfigurationError(f"invalid registration_type: {item.model_id}")
            if item.registration_type == "user_uploaded_unvalidated" and item.status == "available":
                raise CatalogConfigurationError(f"unvalidated model cannot be available: {item.model_id}")
            if item.registration_type == "operator_registered" and item.status == "available":
                file_record = item.file or {}
                if not item.hash or not file_record.get("operator_registered"):
                    raise CatalogConfigurationError(f"operator model lacks verified file/hash: {item.model_id}")
            if item.registration_type == "operator_registered" and item.status not in {"unvalidated", "preparation_only", "blocked", "archived", "available"}:
                raise CatalogConfigurationError(f"invalid operator model status: {item.model_id}")
            if item.status in EXECUTABLE_STATUSES and (not item.adapter_id or not item.entrypoint_id):
                raise CatalogConfigurationError(f"available model lacks controlled executor: {item.model_id}")
            self._items[item.model_id] = item

    def list(self, *, scenario_id: str | None = None, solver: str | None = None, status: str | None = None) -> list[ModelDefinition]:
        return [x for x in self._items.values() if (scenario_id is None or x.scenario_id == scenario_id) and (solver is None or x.solver == solver) and (status is None or x.status == status)]

    def get(self, model_id: str) -> ModelDefinition | None:
        return self._items.get(str(model_id))

    def normalize_inputs(self, model_id: str, inputs: Mapping[str, Any]) -> ModelInputResult:
        model = self.get(model_id)
        if model is None:
            return ModelInputResult(errors=[{"code": "MODEL_NOT_FOUND", "field": "model_id"}])
        return normalize_model_inputs(model, inputs)

    def executable_matlab_dispatcher_ids(self) -> set[str]:
        ids: set[str] = set()
        for item in self._items.values():
            if item.backend != "matlab" or not item.supports_execution or item.status != "available":
                continue
            if not item.dispatcher_model_id or item.matlab_entrypoint != "thermalagent_dispatch":
                raise CatalogConfigurationError(f"executable MATLAB model lacks dispatcher identity: {item.model_id}")
            ids.add(item.dispatcher_model_id)
        return ids

    def validate_scenarios(self, scenario_ids: set[str]) -> None:
        missing = sorted(x.model_id for x in self._items.values() if x.scenario_id not in scenario_ids)
        if missing:
            raise CatalogConfigurationError("models reference unknown scenarios: " + ", ".join(missing))


__all__ = ["EXECUTABLE_STATUSES", "ModelRegistry"]
