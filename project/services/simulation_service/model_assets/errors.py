from __future__ import annotations


class ModelAssetError(Exception):
    code = "model_asset_error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": str(self)}


class ModelAssetDisabledError(ModelAssetError):
    code = "model_asset_feature_disabled"
    status_code = 403


class ModelAssetValidationError(ModelAssetError):
    code = "invalid_model_asset"
    status_code = 422


class ModelAssetNotFoundError(ModelAssetError):
    code = "model_asset_not_found"
    status_code = 404


class ModelAssetTransitionError(ModelAssetError):
    code = "invalid_model_asset_status_transition"
    status_code = 409


class ModelAssetIntegrityError(ModelAssetError):
    code = "model_asset_hash_mismatch"
    status_code = 409


class ModelAssetConflictError(ModelAssetError):
    code = "model_asset_conflict"
    status_code = 409


__all__ = [
    "ModelAssetConflictError",
    "ModelAssetDisabledError",
    "ModelAssetError",
    "ModelAssetIntegrityError",
    "ModelAssetNotFoundError",
    "ModelAssetTransitionError",
    "ModelAssetValidationError",
]
