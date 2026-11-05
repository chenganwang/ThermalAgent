from __future__ import annotations

from typing import Any, BinaryIO, Callable, Mapping

from .audit import ModelAssetAuditLog
from .config import ModelAssetConfig, load_model_asset_config
from .errors import (
    ModelAssetConflictError,
    ModelAssetDisabledError,
    ModelAssetIntegrityError,
    ModelAssetTransitionError,
    ModelAssetValidationError,
)
from .hashing import sha256_file
from .registry import ModelAssetRegistry, RegisteredAssetModelRegistry
from .sanitizer import admin_asset_payload, public_asset_payload
from .schemas import ApprovalRequest, ModelAsset, RegistrationRequest, utc_now_iso
from .storage import ModelAssetStorage
from .validation import ALLOWED_EXTENSIONS, BLOCKED_EXTENSIONS, validate_model_id, validate_upload_metadata


LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "quarantined": frozenset({"pending_review"}),
    "pending_review": frozenset({"approved", "rejected"}),
    "approved": frozenset({"registered", "blocked"}),
    "registered": frozenset({"blocked"}),
    "blocked": frozenset({"archived"}),
    "rejected": frozenset(),
    "archived": frozenset(),
}


class ModelAssetLifecycleService:
    def __init__(
        self,
        config: ModelAssetConfig | None = None,
        *,
        storage: ModelAssetStorage | None = None,
        assets: ModelAssetRegistry | None = None,
        registered_models: RegisteredAssetModelRegistry | None = None,
        audit: ModelAssetAuditLog | None = None,
        scenario_exists: Callable[[str], bool] | None = None,
        model_id_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.config = config or load_model_asset_config()
        self.storage = storage or ModelAssetStorage(self.config)
        self.assets = assets or ModelAssetRegistry(self.config)
        self.registered_models = registered_models or RegisteredAssetModelRegistry(self.config)
        self.audit = audit or ModelAssetAuditLog(self.config)
        self._scenario_exists = scenario_exists or _default_scenario_exists
        self._model_id_exists = model_id_exists or _default_model_id_exists

    def capabilities(self) -> dict[str, Any]:
        return {
            "upload_enabled": self.config.upload_enabled,
            "admin_enabled": self.config.admin_enabled,
            "max_file_size_bytes": self.config.max_file_size_bytes,
            "max_file_size_mb": self.config.max_file_size_mb,
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "blocked_extensions": sorted(BLOCKED_EXTENSIONS),
            "execution_allowed": False,
            "preview_mode": "metadata_only",
        }

    def upload(
        self,
        *,
        filename: str,
        source: BinaryIO | bytes,
        mime_type: str | None = None,
        uploaded_by: str = "user",
        metadata: Mapping[str, Any] | None = None,
        allow_matlab_source_quarantine: bool = False,
    ) -> ModelAsset:
        self._require_upload_enabled()
        internal_id = self.storage.new_asset_id()
        try:
            safe_metadata = validate_upload_metadata(metadata)
            asset = self.storage.store_quarantined(
                filename=filename, source=source, mime_type=mime_type, uploaded_by=uploaded_by,
                metadata=safe_metadata, asset_id=internal_id,
                allow_matlab_source_quarantine=allow_matlab_source_quarantine,
            )
            self.assets.save(asset)
        except Exception as exc:
            self.audit.append(
                action="upload", asset_id=internal_id, previous_status=None, new_status=None,
                actor_type="user", success=False, reason=getattr(exc, "code", type(exc).__name__),
            )
            raise
        self.audit.append(
            action="upload", asset_id=asset.asset_id, previous_status=None, new_status="quarantined",
            actor_type="user", reason="asset_stored_in_quarantine",
        )
        return asset

    def submit_review(self, asset_id: str) -> ModelAsset:
        self._require_upload_enabled()
        asset = self.assets.get(asset_id)
        previous = asset.status
        self._transition(asset, "pending_review")
        self.assets.save(asset)
        self.audit.append(
            action="submit_review", asset_id=asset.asset_id, previous_status=previous,
            new_status=asset.status, actor_type="user", reason="submitted_for_operator_review",
        )
        return asset

    def approve(self, asset_id: str, request: ApprovalRequest, *, operator: str = "operator") -> ModelAsset:
        self._require_admin_enabled()
        asset = self.assets.get(asset_id)
        self._require_status(asset, "pending_review")
        self._verify_integrity(asset, actor_type="operator")
        scenario_id = str(request.scenario_id or "").strip()
        if not scenario_id or not self._scenario_exists(scenario_id):
            raise ModelAssetValidationError("Approval requires a registered scenario_id.", code="model_asset_scenario_not_found")
        proposed_model_id = validate_model_id(request.proposed_model_id)
        previous = asset.status
        self.storage.move_to_approved(asset)
        asset.status = "approved"
        asset.approved_at = utc_now_iso()
        asset.approved_by = str(operator or "operator")[:200]
        asset.approved_sha256 = asset.sha256
        asset.scenario_id = scenario_id
        asset.proposed_model_id = proposed_model_id
        asset.operator_notes = str(request.operator_notes or "")[:2000] or None
        asset.execution_allowed = False
        asset.human_validated = False
        self.assets.save(asset)
        self.audit.append(
            action="approve", asset_id=asset.asset_id, previous_status=previous, new_status="approved",
            actor_type="operator", reason="operator_approved_file_only_execution_still_disabled",
        )
        return asset

    def reject(self, asset_id: str, reason: str, *, operator: str = "operator") -> ModelAsset:
        self._require_admin_enabled()
        asset = self.assets.get(asset_id)
        self._require_status(asset, "pending_review")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ModelAssetValidationError("A rejection reason is required.", code="model_asset_rejection_reason_required")
        previous = asset.status
        self.storage.move_to_rejected(asset)
        asset.status = "rejected"
        asset.rejected_at = utc_now_iso()
        asset.rejected_by = str(operator or "operator")[:200]
        asset.rejection_reason = normalized_reason[:2000]
        asset.execution_allowed = False
        self.assets.save(asset)
        self.audit.append(
            action="reject", asset_id=asset.asset_id, previous_status=previous, new_status="rejected",
            actor_type="operator", reason="operator_rejected_asset",
        )
        return asset

    def block(self, asset_id: str, reason: str = "operator_blocked", *, actor_type: str = "operator") -> ModelAsset:
        self._require_admin_enabled()
        asset = self.assets.get(asset_id)
        if asset.status not in {"approved", "registered"}:
            raise ModelAssetTransitionError(f"Cannot block asset from {asset.status}.")
        previous = asset.status
        asset.status = "blocked"
        asset.execution_allowed = False
        if asset.registered_model_id:
            self.registered_models.set_status(asset.registered_model_id, "blocked")
        self.assets.save(asset)
        self.audit.append(
            action="block", asset_id=asset.asset_id, previous_status=previous, new_status="blocked",
            actor_type=actor_type, reason="operator_blocked_asset" if actor_type == "operator" else "system_blocked_asset",
        )
        return asset

    def enable_preparation_only(self, asset_id: str, *, operator: str = "operator") -> ModelAsset:
        """Restore a blocked registered file to catalog preparation-only visibility.

        This never creates an executor entrypoint and never permits execution.
        """

        self._require_admin_enabled()
        asset = self.assets.get(asset_id)
        if asset.status != "blocked" or not asset.registered_model_id:
            raise ModelAssetTransitionError(
                "Only a blocked registered file model can be enabled as preparation_only."
            )
        previous = asset.status
        self.registered_models.set_status(asset.registered_model_id, "preparation_only")
        asset.status = "registered"
        asset.execution_allowed = False
        asset.human_validated = False
        self.assets.save(asset)
        self.audit.append(
            action="enable_preparation_only",
            asset_id=asset.asset_id,
            previous_status=previous,
            new_status="registered",
            actor_type="operator",
            reason="restored_catalog_visibility_execution_still_disabled",
        )
        return asset

    def archive(self, asset_id: str, *, operator: str = "operator") -> ModelAsset:
        self._require_admin_enabled()
        asset = self.assets.get(asset_id)
        previous = asset.status
        self._transition(asset, "archived")
        asset.execution_allowed = False
        self.assets.save(asset)
        self.audit.append(
            action="archive", asset_id=asset.asset_id, previous_status=previous, new_status="archived",
            actor_type="operator", reason="operator_archived_blocked_asset",
        )
        return asset

    def register(
        self,
        asset_id: str,
        request: RegistrationRequest,
        *,
        operator: str = "operator",
    ) -> dict[str, Any]:
        self._require_admin_enabled()
        asset = self.assets.get(asset_id)
        self._require_status(asset, "approved")
        self._verify_integrity(asset, actor_type="operator")
        if not request.operator_confirmation:
            raise ModelAssetValidationError("Operator confirmation is required.", code="model_asset_operator_confirmation_required")
        if request.status not in {"unvalidated", "preparation_only"}:
            raise ModelAssetValidationError("Registered file models must remain unvalidated or preparation_only.", code="unsafe_registered_model_status")
        solver = str(request.solver or "").strip().lower()
        if not solver:
            raise ModelAssetValidationError("A solver classification is required.", code="registered_model_solver_required")
        if asset.approved_sha256 != asset.sha256:
            self._block_hash_mismatch(asset, actor_type="operator")
        model_id = validate_model_id(asset.proposed_model_id or "")
        if self._model_id_exists(model_id) or self.registered_models.get(model_id) is not None:
            raise ModelAssetConflictError(f"model_id already exists: {model_id}", code="registered_model_id_conflict")
        allowed_inputs = [str(item).strip() for item in request.allowed_inputs if str(item).strip()]
        model = {
            "model_id": model_id,
            "scenario_id": asset.scenario_id,
            "name_zh": asset.original_filename,
            "solver": solver,
            "version": str(request.version or "0.1.0"),
            "status": request.status,
            "asset_id": asset.asset_id,
            "sha256": asset.sha256,
            "hash": asset.sha256,
            "execution_mode": "registered_file",
            "adapter_id": str(request.adapter_id).strip() if request.adapter_id else None,
            "entrypoint_id": None,
            "allowed_inputs": allowed_inputs,
            "outputs": [],
            "human_validated": False,
            "execution_allowed": False,
            "registration_type": "operator_registered",
            "file": {
                "asset_id": asset.asset_id,
                "filename": asset.original_filename,
                "sha256": asset.sha256,
                "operator_registered": True,
            },
            "source": {"type": "operator_registered_asset", "asset_id": asset.asset_id},
            "assumptions": [],
            "limitations": ["Registered file is not execution-certified and cannot run."],
            "registered_at": utc_now_iso(),
        }
        saved_model = self.registered_models.add(model)
        previous = asset.status
        asset.status = "registered"
        asset.registered_model_id = model_id
        asset.execution_allowed = False
        asset.human_validated = False
        self.assets.save(asset)
        self.audit.append(
            action="register", asset_id=asset.asset_id, previous_status=previous, new_status="registered",
            actor_type="operator", reason="registered_as_non_executable_file_model",
        )
        return saved_model

    def get_public(self, asset_id: str) -> dict[str, Any]:
        return public_asset_payload(self.assets.get(asset_id))

    def list_public(self, *, status: str | None = None) -> list[dict[str, Any]]:
        return [public_asset_payload(asset) for asset in self.assets.list(status=status)]

    def get_admin(self, asset_id: str) -> dict[str, Any]:
        self._require_admin_enabled()
        return admin_asset_payload(self.assets.get(asset_id))

    def list_admin(self, *, status: str | None = None) -> list[dict[str, Any]]:
        self._require_admin_enabled()
        return [admin_asset_payload(asset) for asset in self.assets.list(status=status)]

    def verify_integrity(self, asset_id: str, *, actor_type: str = "system") -> bool:
        asset = self.assets.get(asset_id)
        self._verify_integrity(asset, actor_type=actor_type)
        return True

    def _verify_integrity(self, asset: ModelAsset, *, actor_type: str) -> None:
        current_hash = sha256_file(self.storage.locate(asset))
        expected = asset.approved_sha256 if asset.status in {"approved", "registered", "blocked", "archived"} else asset.sha256
        if current_hash != expected or current_hash != asset.sha256:
            self._block_hash_mismatch(asset, actor_type=actor_type)

    def _block_hash_mismatch(self, asset: ModelAsset, *, actor_type: str) -> None:
        previous = asset.status
        asset.status = "blocked"
        asset.execution_allowed = False
        self.assets.save(asset)
        self.audit.append(
            action="hash_mismatch", asset_id=asset.asset_id, previous_status=previous, new_status="blocked",
            actor_type=actor_type, reason="sha256_mismatch",
        )
        raise ModelAssetIntegrityError("Model asset SHA-256 no longer matches its registered metadata.")

    @staticmethod
    def _require_status(asset: ModelAsset, expected: str) -> None:
        if asset.status != expected:
            raise ModelAssetTransitionError(f"Asset must be {expected}; current status is {asset.status}.")

    @staticmethod
    def _transition(asset: ModelAsset, new_status: str) -> None:
        if new_status not in LEGAL_TRANSITIONS.get(asset.status, frozenset()):
            raise ModelAssetTransitionError(f"Illegal asset transition: {asset.status} -> {new_status}")
        asset.status = new_status
        asset.execution_allowed = False

    def _require_upload_enabled(self) -> None:
        if not self.config.upload_enabled:
            raise ModelAssetDisabledError("Model asset upload is disabled by default.", code="model_asset_upload_disabled")

    def _require_admin_enabled(self) -> None:
        if not self.config.admin_enabled:
            raise ModelAssetDisabledError("Model asset administration is disabled by default.", code="model_asset_admin_disabled")


def _default_scenario_exists(scenario_id: str) -> bool:
    try:
        from ..catalog import ScenarioCatalog

        return ScenarioCatalog().get(scenario_id) is not None
    except Exception:
        return False


def _default_model_id_exists(model_id: str) -> bool:
    try:
        from ..catalog import ModelRegistry

        return ModelRegistry().get(model_id) is not None
    except Exception:
        return False


__all__ = ["LEGAL_TRANSITIONS", "ModelAssetLifecycleService"]
