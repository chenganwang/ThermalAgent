from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from .config import ModelAssetConfig
from .errors import ModelAssetNotFoundError, ModelAssetValidationError
from .schemas import ModelAsset
from .validation import validate_and_normalize_filename, validate_asset_id, validate_mime_type, validate_size


class ModelAssetStorage:
    """Opaque binary storage. It never parses, imports, extracts, or executes an asset."""

    def __init__(self, config: ModelAssetConfig) -> None:
        self.config = config

    @staticmethod
    def new_asset_id() -> str:
        return f"asset-{uuid4().hex}"

    def store_quarantined(
        self,
        *,
        filename: str,
        source: BinaryIO | bytes,
        mime_type: str | None = None,
        uploaded_by: str = "user",
        metadata: dict[str, object] | None = None,
        asset_id: str | None = None,
        allow_matlab_source_quarantine: bool = False,
    ) -> ModelAsset:
        normalized_name, extension, asset_type = validate_and_normalize_filename(
            filename,
            allow_matlab_source_quarantine=allow_matlab_source_quarantine,
        )
        normalized_mime = validate_mime_type(
            extension,
            mime_type,
            allow_matlab_source_quarantine=allow_matlab_source_quarantine,
        )
        internal_id = validate_asset_id(asset_id) if asset_id else self.new_asset_id()
        stored_filename = f"{internal_id}{extension}"
        stream = BytesIO(source) if isinstance(source, bytes) else source
        if not hasattr(stream, "read"):
            raise ModelAssetValidationError("Upload source must be a binary stream.", code="invalid_model_asset_stream")
        self.config.quarantine_dir.mkdir(parents=True, exist_ok=True)
        target = self._safe_child(self.config.quarantine_dir, stored_filename)
        temporary = self._safe_child(self.config.quarantine_dir, f".{internal_id}.uploading")
        digest = sha256()
        size = 0
        try:
            with temporary.open("xb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise ModelAssetValidationError("Upload stream must return bytes.", code="invalid_model_asset_stream")
                    size += len(chunk)
                    if size > self.config.max_file_size_bytes:
                        raise ModelAssetValidationError("Model asset exceeds the configured size limit.", code="model_asset_too_large")
                    digest.update(chunk)
                    handle.write(chunk)
            validate_size(size, self.config.max_file_size_bytes)
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return ModelAsset(
            asset_id=internal_id,
            original_filename=normalized_name,
            stored_filename=stored_filename,
            asset_type=asset_type,
            extension=extension,
            mime_type=normalized_mime,
            size_bytes=size,
            sha256=digest.hexdigest(),
            uploaded_by=str(uploaded_by or "user")[:200],
            metadata=dict(metadata or {}),
        )

    def locate(self, asset: ModelAsset) -> Path:
        validate_asset_id(asset.asset_id)
        candidates = (
            self._safe_child(self.config.quarantine_dir, asset.stored_filename),
            self._safe_child(self.config.approved_dir, asset.stored_filename),
            self._safe_child(self.config.rejected_dir, asset.stored_filename),
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ModelAssetNotFoundError("Model asset binary is missing.", code="model_asset_binary_not_found")

    def move_to_approved(self, asset: ModelAsset) -> None:
        self._move(asset, self.config.approved_dir)

    def move_to_rejected(self, asset: ModelAsset) -> None:
        self._move(asset, self.config.rejected_dir)

    def _move(self, asset: ModelAsset, destination_dir: Path) -> None:
        source = self.locate(asset)
        destination_dir.mkdir(parents=True, exist_ok=True)
        target = self._safe_child(destination_dir, asset.stored_filename)
        if target.exists() and target != source:
            raise ModelAssetValidationError("Asset storage target already exists.", code="model_asset_storage_conflict")
        if source != target:
            source.replace(target)

    @staticmethod
    def _safe_child(directory: Path, filename: str) -> Path:
        if not filename or any(separator in filename for separator in ("/", "\\")) or ".." in filename:
            raise ModelAssetValidationError("Unsafe internal asset filename.", code="unsafe_internal_asset_filename")
        root = Path(directory).resolve()
        child = (root / filename).resolve()
        try:
            child.relative_to(root)
        except ValueError as exc:
            raise ModelAssetValidationError("Asset path escaped its storage root.", code="unsafe_model_asset_storage_path") from exc
        return child


__all__ = ["ModelAssetStorage"]
