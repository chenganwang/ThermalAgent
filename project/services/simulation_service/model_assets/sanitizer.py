from __future__ import annotations

import os
import re
from typing import Any, Mapping

from .schemas import ModelAsset


PUBLIC_ASSET_FIELDS = (
    "asset_id", "original_filename", "asset_type", "extension", "mime_type", "size_bytes", "sha256",
    "status", "uploaded_at", "approved_at", "rejected_at", "rejection_reason", "operator_notes",
    "scenario_id", "proposed_model_id", "registered_model_id", "execution_allowed", "human_validated",
    "security_scan_status", "metadata",
)
ADMIN_ASSET_FIELDS = PUBLIC_ASSET_FIELDS + ("stored_filename", "uploaded_by", "approved_by", "rejected_by", "updated_at", "approved_sha256")
_SENSITIVE_KEY_PARTS = ("password", "token", "secret", "license")


def public_asset_payload(asset: ModelAsset | Mapping[str, Any]) -> dict[str, Any]:
    raw = asset.to_dict() if isinstance(asset, ModelAsset) else dict(asset)
    return sanitize_mapping({name: raw.get(name) for name in PUBLIC_ASSET_FIELDS})


def admin_asset_payload(asset: ModelAsset | Mapping[str, Any]) -> dict[str, Any]:
    raw = asset.to_dict() if isinstance(asset, ModelAsset) else dict(asset)
    return sanitize_mapping({name: raw.get(name) for name in ADMIN_ASSET_FIELDS})


def public_registered_model_payload(model: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(model)
    raw.pop("registered_by", None)
    return sanitize_mapping(raw)


def admin_registered_model_payload(model: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_mapping(dict(model))


def sanitize_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): sanitize_mapping(item) for key, item in value.items() if not _sensitive_key(str(key))}
    if isinstance(value, list):
        return [sanitize_mapping(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_mapping(item) for item in value]
    if isinstance(value, str):
        return _redact_path(value)
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in {"path", "absolute_path", "local_path", "admin_token", "evidence_path"} or lowered.endswith("_path") or any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _redact_path(value: str) -> str:
    admin_token = os.getenv("ADMIN_FEATURE_FLAGS_TOKEN", "").strip()
    if admin_token:
        value = value.replace(admin_token, "[redacted_secret]")
    value = re.sub(r"(?i)\b[a-z]:[\\/][^\s,;\]\[{}]+", "[redacted_local_path]", value)
    value = re.sub(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+", "Bearer [redacted_secret]", value)
    value = re.sub(r"(?i)file://\S+", "[redacted_local_path]", value)
    if value.startswith("\\\\"):
        return "[redacted_local_path]"
    return value


__all__ = [
    "ADMIN_ASSET_FIELDS", "PUBLIC_ASSET_FIELDS", "admin_asset_payload", "admin_registered_model_payload",
    "public_asset_payload", "public_registered_model_payload", "sanitize_mapping",
]
