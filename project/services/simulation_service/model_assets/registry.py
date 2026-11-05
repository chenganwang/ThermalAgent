from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .config import ModelAssetConfig
from .errors import ModelAssetConflictError, ModelAssetNotFoundError, ModelAssetValidationError
from .schemas import ASSET_STATUSES, ModelAsset, utc_now_iso
from .validation import validate_asset_id, validate_model_id


class ModelAssetRegistry:
    def __init__(self, config: ModelAssetConfig) -> None:
        self.config = config

    def save(self, asset: ModelAsset) -> ModelAsset:
        validate_asset_id(asset.asset_id)
        if asset.status not in ASSET_STATUSES:
            raise ModelAssetValidationError(f"Invalid asset status: {asset.status}", code="invalid_model_asset_status")
        asset.execution_allowed = False
        asset.human_validated = False
        asset.updated_at = utc_now_iso()
        self.config.metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self._metadata_path(asset.asset_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(asset.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return asset

    def get(self, asset_id: str) -> ModelAsset:
        path = self._metadata_path(validate_asset_id(asset_id))
        if not path.is_file():
            raise ModelAssetNotFoundError(f"Unknown model asset: {asset_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ModelAssetValidationError("Model asset metadata is unreadable.", code="model_asset_metadata_unreadable") from exc
        return ModelAsset.from_dict(payload)

    def list(self, *, status: str | None = None) -> list[ModelAsset]:
        if not self.config.metadata_dir.exists():
            return []
        items: list[ModelAsset] = []
        for path in sorted(self.config.metadata_dir.glob("asset-*.json")):
            try:
                asset = ModelAsset.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if status is None or asset.status == status:
                items.append(asset)
        return sorted(items, key=lambda item: item.uploaded_at, reverse=True)

    def _metadata_path(self, asset_id: str) -> Path:
        return (self.config.metadata_dir / f"{asset_id}.json").resolve()


class RegisteredAssetModelRegistry:
    """Runtime registry for operator-approved, non-executable file models."""

    def __init__(self, config: ModelAssetConfig) -> None:
        self.config = config

    def list(self) -> list[dict[str, Any]]:
        if not self.config.registered_models_path.is_file():
            return []
        try:
            payload = json.loads(self.config.registered_models_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelAssetValidationError("Registered model metadata is unreadable.", code="registered_model_registry_unreadable") from exc
        return [dict(item) for item in payload.get("models") or () if isinstance(item, Mapping)]

    def get(self, model_id: str) -> dict[str, Any] | None:
        normalized = validate_model_id(model_id)
        return next((item for item in self.list() if item.get("model_id") == normalized), None)

    def add(self, model: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(model)
        model_id = validate_model_id(str(item.get("model_id") or ""))
        models = self.list()
        if any(existing.get("model_id") == model_id for existing in models):
            raise ModelAssetConflictError(f"Registered model_id already exists: {model_id}", code="registered_model_id_conflict")
        item["model_id"] = model_id
        item["status"] = "preparation_only" if item.get("status") == "preparation_only" else "unvalidated"
        item["execution_allowed"] = False
        item["human_validated"] = False
        models.append(item)
        path = self.config.registered_models_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"registry_version": "7E.1", "updated_at": utc_now_iso(), "models": models}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return dict(item)

    def set_status(self, model_id: str, status: str) -> dict[str, Any]:
        """Update only the non-executable catalog visibility state."""

        normalized_id = validate_model_id(model_id)
        normalized_status = str(status or "").strip()
        if normalized_status not in {"preparation_only", "blocked", "archived"}:
            raise ModelAssetValidationError(
                "Registered file models may only use non-executable statuses.",
                code="unsafe_registered_model_status",
            )
        models = self.list()
        selected: dict[str, Any] | None = None
        for item in models:
            if item.get("model_id") != normalized_id:
                continue
            item["status"] = normalized_status
            item["execution_allowed"] = False
            item["human_validated"] = False
            selected = item
            break
        if selected is None:
            raise ModelAssetNotFoundError(
                f"Unknown registered model: {normalized_id}",
                code="registered_model_not_found",
            )
        path = self.config.registered_models_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"registry_version": "7E.1", "updated_at": utc_now_iso(), "models": models}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return dict(selected)


__all__ = ["ModelAssetRegistry", "RegisteredAssetModelRegistry"]
