from __future__ import annotations

from pathlib import PurePath, PurePosixPath, PureWindowsPath
import re
from typing import Any, Mapping

from .errors import ModelAssetValidationError


ALLOWED_EXTENSIONS: dict[str, str] = {
    ".slx": "simulation_model", ".mdl": "simulation_model", ".mat": "data_asset",
    ".stl": "geometry_asset", ".step": "geometry_asset", ".stp": "geometry_asset",
    ".iges": "geometry_asset", ".igs": "geometry_asset",
}
BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".dll", ".bat", ".cmd", ".ps1", ".sh", ".py", ".m", ".jar", ".js",
    ".vbs", ".scr", ".com", ".zip", ".rar", ".7z",
})
GENERIC_MIME_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})
MIME_HINTS: dict[str, frozenset[str]] = {
    ".m": frozenset({"text/plain", "text/x-matlab", "application/x-matlab"}),
    ".slx": frozenset({"application/zip", "application/x-zip-compressed", "application/vnd.mathworks.simulink.model"}),
    ".mdl": frozenset({"text/plain", "application/x-matlab-data"}),
    ".mat": frozenset({"application/x-matlab-data", "application/matlab-mat"}),
    ".stl": frozenset({"model/stl", "application/sla", "application/vnd.ms-pki.stl"}),
    ".step": frozenset({"model/step", "application/step"}),
    ".stp": frozenset({"model/step", "application/step"}),
    ".iges": frozenset({"model/iges", "application/iges"}),
    ".igs": frozenset({"model/iges", "application/iges"}),
}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._()\-\u4e00-\u9fff]+")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_and_normalize_filename(
    filename: str,
    *,
    allow_matlab_source_quarantine: bool = False,
) -> tuple[str, str, str]:
    raw = str(filename or "").strip()
    if not raw:
        raise ModelAssetValidationError("A non-empty filename is required.", code="model_asset_filename_missing")
    windows_path = PureWindowsPath(raw)
    if windows_path.is_absolute() or windows_path.drive or PurePosixPath(raw).is_absolute():
        raise ModelAssetValidationError("Absolute paths are not accepted.", code="model_asset_path_rejected")
    if ".." in raw or any(separator in raw for separator in ("/", "\\")):
        raise ModelAssetValidationError("Path traversal or separators are not accepted.", code="model_asset_path_rejected")
    extension = PurePath(raw).suffix.lower()
    if extension == ".m" and allow_matlab_source_quarantine:
        asset_type = "simulation_model"
    elif extension in BLOCKED_EXTENSIONS:
        raise ModelAssetValidationError(f"Blocked model asset extension: {extension}", code="model_asset_extension_blocked")
    elif extension not in ALLOWED_EXTENSIONS:
        raise ModelAssetValidationError(f"Unsupported model asset extension: {extension or '(none)'}", code="model_asset_extension_not_allowed")
    else:
        asset_type = ALLOWED_EXTENSIONS[extension]
    stem = PurePath(raw).stem.strip()
    sanitized_stem = _SAFE_FILENAME.sub("_", stem).strip(" ._") or "model_asset"
    sanitized = f"{sanitized_stem[:180]}{extension}"
    return sanitized, extension, asset_type


def validate_mime_type(
    extension: str,
    mime_type: str | None,
    *,
    allow_matlab_source_quarantine: bool = False,
) -> str:
    normalized = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized in GENERIC_MIME_TYPES:
        return normalized or "application/octet-stream"
    allowed = MIME_HINTS.get(extension, frozenset())
    if extension == ".m" and not allow_matlab_source_quarantine:
        allowed = frozenset()
    if normalized not in allowed:
        raise ModelAssetValidationError(
            f"MIME type {normalized} is inconsistent with {extension}.",
            code="model_asset_mime_mismatch",
        )
    return normalized


def validate_size(size_bytes: int, max_file_size_bytes: int) -> None:
    if size_bytes <= 0:
        raise ModelAssetValidationError("Empty model asset files are not accepted.", code="model_asset_empty")
    if size_bytes > max_file_size_bytes:
        raise ModelAssetValidationError("Model asset exceeds the configured size limit.", code="model_asset_too_large")


def validate_upload_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(metadata or {})
    forbidden = {"status", "model_id", "proposed_model_id", "registered_model_id", "execution_allowed", "stored_filename", "path", "local_path", "absolute_path"}
    fields = sorted(str(key) for key in normalized if str(key).lower() in forbidden or str(key).lower().endswith("_path"))
    if fields:
        raise ModelAssetValidationError("Upload metadata contains operator-controlled fields: " + ", ".join(fields), code="model_asset_metadata_field_forbidden")
    return normalized


def validate_asset_id(asset_id: str) -> str:
    normalized = str(asset_id or "").strip()
    if not normalized.startswith("asset-") or not _SAFE_ID.fullmatch(normalized):
        raise ModelAssetValidationError("Invalid asset_id.", code="invalid_model_asset_id")
    return normalized


def validate_model_id(model_id: str) -> str:
    normalized = str(model_id or "").strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ModelAssetValidationError("Invalid proposed model_id.", code="invalid_proposed_model_id")
    return normalized


__all__ = [
    "ALLOWED_EXTENSIONS", "BLOCKED_EXTENSIONS", "validate_and_normalize_filename",
    "validate_asset_id", "validate_mime_type", "validate_model_id", "validate_size", "validate_upload_metadata",
]
