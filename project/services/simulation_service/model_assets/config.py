from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .errors import ModelAssetValidationError


DEFAULT_ASSET_ROOT = Path("runtime/simulation/model_assets")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw and raw.strip() else default
    except ValueError:
        return default


@dataclass(frozen=True)
class ModelAssetConfig:
    upload_enabled: bool
    admin_enabled: bool
    max_file_size_bytes: int
    quarantine_dir: Path
    approved_dir: Path
    rejected_dir: Path
    metadata_dir: Path
    audit_path: Path
    registered_models_path: Path
    project_root: Path

    @property
    def max_file_size_mb(self) -> float:
        return self.max_file_size_bytes / (1024 * 1024)

    @classmethod
    def for_root(
        cls,
        root: Path,
        *,
        upload_enabled: bool = True,
        admin_enabled: bool = True,
        max_file_size_bytes: int = 100 * 1024 * 1024,
    ) -> "ModelAssetConfig":
        base = Path(root).resolve()
        return cls(
            upload_enabled=upload_enabled,
            admin_enabled=admin_enabled,
            max_file_size_bytes=max_file_size_bytes,
            quarantine_dir=base / "quarantine",
            approved_dir=base / "approved",
            rejected_dir=base / "rejected",
            metadata_dir=base / "metadata",
            audit_path=base / "audit" / "model_asset_audit.jsonl",
            registered_models_path=base / "registered_models.json",
            project_root=base,
        )


def load_model_asset_config(project_root: Path | None = None) -> ModelAssetConfig:
    root = (project_root or Path(__file__).resolve().parents[3]).resolve()
    asset_root = (root / DEFAULT_ASSET_ROOT).resolve()

    def configured(name: str, default: Path) -> Path:
        raw = os.getenv(name)
        path = Path(raw) if raw else default
        resolved = (path if path.is_absolute() else root / path).resolve()
        try:
            resolved.relative_to(asset_root)
        except ValueError as exc:
            raise ModelAssetValidationError(
                f"{name} must remain under runtime/simulation/model_assets.",
                code="unsafe_model_asset_storage_path",
            ) from exc
        return resolved

    max_mb = _env_int("SIMULATION_MODEL_MAX_FILE_SIZE_MB", 100)
    if max_mb <= 0:
        max_mb = 100
    config = ModelAssetConfig(
        upload_enabled=_env_bool("SIMULATION_MODEL_UPLOAD_ENABLED", False),
        admin_enabled=_env_bool("SIMULATION_MODEL_ADMIN_ENABLED", False),
        max_file_size_bytes=max_mb * 1024 * 1024,
        quarantine_dir=configured("SIMULATION_MODEL_QUARANTINE_DIR", DEFAULT_ASSET_ROOT / "quarantine"),
        approved_dir=configured("SIMULATION_MODEL_APPROVED_DIR", DEFAULT_ASSET_ROOT / "approved"),
        rejected_dir=configured("SIMULATION_MODEL_REJECTED_DIR", DEFAULT_ASSET_ROOT / "rejected"),
        metadata_dir=configured("SIMULATION_MODEL_METADATA_DIR", DEFAULT_ASSET_ROOT / "metadata"),
        audit_path=configured("SIMULATION_MODEL_AUDIT_PATH", DEFAULT_ASSET_ROOT / "audit" / "model_asset_audit.jsonl"),
        registered_models_path=asset_root / "registered_models.json",
        project_root=root,
    )
    if len({config.quarantine_dir, config.approved_dir, config.rejected_dir, config.metadata_dir}) != 4:
        raise ModelAssetValidationError("Model asset storage directories must be distinct.", code="overlapping_model_asset_paths")
    return config


__all__ = ["DEFAULT_ASSET_ROOT", "ModelAssetConfig", "load_model_asset_config"]
