from __future__ import annotations

import re
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from services.simulation_service.model_assets import (
    ApprovalRequest,
    ModelAssetLifecycleService,
    RegistrationRequest,
    admin_asset_payload,
)

from ..contracts import AdminAPIError


_MODEL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,127}$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_ENTRY_POINT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_REQUIRED_FIELDS = frozenset({
    "model_id", "version", "display_name", "description", "backend", "entry_point", "inputs", "outputs",
    "units", "constraints", "execution_type",
})


class ModelManifestValidator:
    def validate(self, manifest: Mapping[str, Any] | None) -> dict[str, Any]:
        raw = dict(manifest or {})
        errors: list[dict[str, Any]] = []
        missing = sorted(_REQUIRED_FIELDS - set(raw))
        if missing:
            errors.append({"code": "manifest_missing_fields", "fields": missing})
        unknown = sorted(set(raw) - (_REQUIRED_FIELDS | {"scenario_id", "examples", "limitations", "assumptions"}))
        if unknown:
            errors.append({"code": "manifest_unknown_fields", "fields": unknown})
        model_id = str(raw.get("model_id") or "").strip()
        version = str(raw.get("version") or "").strip()
        entry_point = str(raw.get("entry_point") or "").strip()
        backend = str(raw.get("backend") or "").strip().lower()
        execution_type = str(raw.get("execution_type") or "").strip().lower()
        if model_id and not _MODEL_ID.fullmatch(model_id):
            errors.append({"code": "manifest_model_id_invalid"})
        if version and not _VERSION.fullmatch(version):
            errors.append({"code": "manifest_version_invalid"})
        if entry_point and not _ENTRY_POINT.fullmatch(entry_point):
            errors.append({"code": "manifest_entry_point_invalid"})
        if backend and backend != "matlab":
            errors.append({"code": "manifest_backend_unsupported"})
        if execution_type and execution_type not in {"preparation_only", "deterministic"}:
            errors.append({"code": "manifest_execution_type_invalid"})
        for field in ("inputs", "outputs", "units"):
            value = raw.get(field)
            if field in raw and (not isinstance(value, dict) or not value):
                errors.append({"code": f"manifest_{field}_invalid"})
        constraints = raw.get("constraints")
        if "constraints" in raw and not isinstance(constraints, (dict, list)):
            errors.append({"code": "manifest_constraints_invalid"})
        if isinstance(raw.get("inputs"), dict):
            for name, contract in raw["inputs"].items():
                if not _ENTRY_POINT.fullmatch(str(name)) or not isinstance(contract, dict):
                    errors.append({"code": "manifest_input_contract_invalid", "field": str(name)})
                    continue
                if contract.get("type") not in {"number", "integer", "boolean", "string"}:
                    errors.append({"code": "manifest_input_type_invalid", "field": str(name)})
        normalized = {
            **raw,
            "model_id": model_id,
            "version": version,
            "entry_point": entry_point,
            "backend": backend,
            "execution_type": execution_type,
        }
        codes = list(dict.fromkeys(str(item["code"]) for item in errors))
        return {"valid": not errors, "manifest": normalized, "errors": errors, "error_codes": codes}


class MatlabStaticSafetyScanner:
    _checks = (
        ("MATLAB_EVAL_FORBIDDEN", re.compile(r"\b(?:eval|evalin)\s*\(", re.IGNORECASE), "Dynamic evaluation is forbidden."),
        ("MATLAB_SYSTEM_FORBIDDEN", re.compile(r"\b(?:system|unix|dos)\s*\(", re.IGNORECASE), "OS command execution is forbidden."),
        ("MATLAB_DYNAMIC_FEVAL_FORBIDDEN", re.compile(r"\bfeval\s*\(\s*(?!['\"])", re.IGNORECASE), "Dynamic feval targets are forbidden."),
        ("MATLAB_SHELL_ESCAPE_FORBIDDEN", re.compile(r"(?m)(?:^|;)\s*!"), "MATLAB shell escape is forbidden."),
        ("MATLAB_PATH_MUTATION_FORBIDDEN", re.compile(r"\b(?:addpath|rmpath|path|cd)\s*\(", re.IGNORECASE), "Dynamic path mutation is forbidden."),
        ("MATLAB_ARBITRARY_FILE_EXECUTION_FORBIDDEN", re.compile(r"\b(?:run|source)\s*\(", re.IGNORECASE), "Arbitrary file execution is forbidden."),
        ("MATLAB_FILE_MUTATION_FORBIDDEN", re.compile(r"\b(?:delete|copyfile|movefile|fopen)\s*\(", re.IGNORECASE), "Arbitrary file operations are forbidden."),
    )

    def scan(self, source: str | bytes) -> dict[str, Any]:
        text = source.decode("utf-8", errors="replace") if isinstance(source, bytes) else str(source or "")
        findings: list[dict[str, Any]] = []
        for code, pattern, message in self._checks:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append({"code": code, "line": line, "message": message, "severity": "error"})
        return {
            "passed": not findings,
            "findings": findings,
            "scanner": "thermalagent_matlab_static_v1",
            "sandbox": False,
            "limitations": ["Static scanning is one defense and does not certify execution safety."],
        }


class MatlabModelContractValidator:
    _function = re.compile(
        r"(?mi)^\s*function\s+(?:(?:\[[^\]]+\]|[A-Za-z][A-Za-z0-9_]*)\s*=\s*)?([A-Za-z][A-Za-z0-9_]*)\s*\("
    )

    def validate(self, *, filename: str, source: str | bytes, manifest: Mapping[str, Any]) -> dict[str, Any]:
        text = source.decode("utf-8", errors="replace") if isinstance(source, bytes) else str(source or "")
        expected = str(manifest.get("entry_point") or "").strip()
        filename_entry = Path(str(filename or "")).stem
        match = self._function.search(text)
        declared = match.group(1) if match else None
        errors: list[dict[str, Any]] = []
        if not declared:
            errors.append({"code": "MATLAB_PRIMARY_FUNCTION_REQUIRED", "message": "A primary MATLAB function declaration is required."})
        if filename_entry != expected or declared != expected:
            errors.append({
                "code": "MATLAB_ENTRY_POINT_MISMATCH",
                "message": "Manifest entry_point, filename, and primary MATLAB function must match.",
            })
        error_codes = list(dict.fromkeys(str(item["code"]) for item in errors))
        return {
            "passed": not errors,
            "entry_point": expected,
            "filename_entry_point": filename_entry,
            "declared_entry_point": declared,
            "errors": errors,
            "error_codes": error_codes,
        }


def manifest_identity(manifest: Mapping[str, Any]) -> tuple[str, str]:
    return str(manifest.get("model_id") or ""), str(manifest.get("version") or "")


class ModelAdminService:
    """Control-plane adapter over the existing non-executing asset lifecycle."""

    def __init__(
        self,
        lifecycle: ModelAssetLifecycleService | None = None,
        *,
        validator: ModelManifestValidator | None = None,
        scanner: MatlabStaticSafetyScanner | None = None,
        contract_validator: MatlabModelContractValidator | None = None,
    ) -> None:
        self.lifecycle = lifecycle or ModelAssetLifecycleService()
        self.validator = validator or ModelManifestValidator()
        self.scanner = scanner or MatlabStaticSafetyScanner()
        self.contract_validator = contract_validator or MatlabModelContractValidator()
        self._lock = RLock()

    def capabilities(self) -> dict[str, Any]:
        base = dict(self.lifecycle.capabilities())
        base.update({
            "manifest_required": True,
            "static_scanner": "thermalagent_matlab_static_v1",
            "custom_execution": "requires_infrastructure",
            "custom_enable": "requires_infrastructure",
            "custom_rollback": "requires_infrastructure",
            "real_matlab_smoke_default": False,
        })
        return base

    def upload_and_validate(
        self,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None,
        manifest: Mapping[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        if Path(str(filename or "")).suffix.lower() != ".m":
            raise AdminAPIError("MODEL_FILE_TYPE_UNSUPPORTED", "Admin V1 accepts MATLAB .m model source only.", status_code=422)
        manifest_result = self.validator.validate(manifest)
        if not manifest_result["valid"]:
            raise AdminAPIError(
                "MODEL_MANIFEST_INVALID", "Model manifest is invalid.", status_code=422,
                details={"error_codes": manifest_result["error_codes"], "errors": manifest_result["errors"]},
            )
        static_result = self.scanner.scan(content)
        normalized = manifest_result["manifest"]
        contract_result = self.contract_validator.validate(filename=filename, source=content, manifest=normalized)
        model_id, version = manifest_identity(normalized)
        with self._lock:
            for existing in self.lifecycle.assets.list():
                existing_manifest = existing.metadata.get("manifest") if isinstance(existing.metadata, dict) else None
                if isinstance(existing_manifest, dict) and manifest_identity(existing_manifest) == (model_id, version):
                    raise AdminAPIError("MODEL_VERSION_CONFLICT", "This model version already exists.", status_code=409)
            try:
                asset = self.lifecycle.upload(
                    filename=filename,
                    source=content,
                    mime_type=mime_type,
                    uploaded_by=actor_id,
                    metadata={"manifest": normalized, "validation": {"manifest": manifest_result, "static": static_result, "contract": contract_result}},
                    allow_matlab_source_quarantine=True,
                )
            except Exception as exc:
                raise _model_error(exc) from exc
            validation_passed = bool(static_result["passed"] and contract_result["passed"])
            asset.security_scan_status = "passed" if static_result["passed"] else "failed"
            asset.metadata = {
                **dict(asset.metadata or {}),
                "manifest": normalized,
                "validation": {"manifest": manifest_result, "static": static_result, "contract": contract_result},
                "validation_status": "passed" if validation_passed else "validation_failed",
                "execution_certification": "not_available",
            }
            self.lifecycle.assets.save(asset)
            if validation_passed:
                try:
                    asset = self.lifecycle.submit_review(asset.asset_id)
                except Exception as exc:
                    raise _model_error(exc) from exc
            return self._project(asset)

    def list_models(self, *, status: str | None = None, query: str | None = None, backend: str | None = None) -> dict[str, Any]:
        try:
            assets = self.lifecycle.assets.list()
        except Exception as exc:
            raise _model_error(exc) from exc
        items = [self._project(asset) for asset in assets]
        keyword = str(query or "").strip().casefold()
        if keyword:
            items = [item for item in items if keyword in f"{item.get('model_id')} {item.get('display_name')} {item.get('filename')}".casefold()]
        if status:
            items = [item for item in items if item.get("status") == status]
        if backend:
            items = [item for item in items if item.get("backend") == backend]
        return {"items": items, "total": len(items), "capabilities": self.capabilities()}

    def get_model(self, asset_id: str, *, include_code: bool = False) -> dict[str, Any]:
        try:
            asset = self.lifecycle.assets.get(asset_id)
            payload = self._project(asset)
            payload["version_history"] = self.version_history(payload.get("model_id"))["items"]
            if include_code:
                path = self.lifecycle.storage.locate(asset)
                source = path.read_text(encoding="utf-8", errors="replace")
                payload["code_preview"] = source[:50000]
                payload["code_truncated"] = len(source) > 50000
            return payload
        except AdminAPIError:
            raise
        except Exception as exc:
            raise _model_error(exc) from exc

    def approve(self, asset_id: str, *, scenario_id: str, operator_notes: str, actor_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                asset = self.lifecycle.assets.get(asset_id)
            except Exception as exc:
                raise _model_error(exc) from exc
            validation = asset.metadata.get("validation") if isinstance(asset.metadata, dict) else {}
            if (
                not isinstance(validation, dict)
                or not (validation.get("manifest") or {}).get("valid")
                or not (validation.get("static") or {}).get("passed")
                or not (validation.get("contract") or {}).get("passed")
            ):
                raise AdminAPIError("MODEL_VALIDATION_REQUIRED", "Manifest and static validation must pass before approval.", status_code=409)
            if asset.status in {"approved", "registered"}:
                return self._project(asset)
            try:
                asset = self.lifecycle.approve(
                    asset_id,
                    ApprovalRequest(
                        scenario_id=scenario_id,
                        proposed_model_id=str(asset.metadata["manifest"]["model_id"]),
                        operator_notes=operator_notes,
                    ),
                    operator=actor_id,
                )
            except Exception as exc:
                raise _model_error(exc) from exc
            manifest = asset.metadata["manifest"]
            registration = "not_attempted"
            try:
                self.lifecycle.register(
                    asset_id,
                    RegistrationRequest(
                        solver=str(manifest.get("backend") or "matlab"),
                        adapter_id=None,
                        allowed_inputs=tuple(str(name) for name in (manifest.get("inputs") or {})),
                        operator_confirmation=True,
                        version=str(manifest.get("version") or "0.1.0"),
                        status="preparation_only",
                    ),
                    operator=actor_id,
                )
                asset = self.lifecycle.assets.get(asset_id)
                registration = "preparation_only"
            except Exception as exc:
                # A canonical model-id/version conflict leaves the safely approved
                # file non-executable; it never widens the runtime allowlist.
                registration = f"not_available:{getattr(exc, 'code', type(exc).__name__)}"
            payload = self._project(asset)
            payload["registration"] = registration
            return payload

    def reject(self, asset_id: str, *, reason: str, actor_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                asset = self.lifecycle.assets.get(asset_id)
                if asset.status == "rejected":
                    return self._project(asset)
                return self._project(self.lifecycle.reject(asset_id, reason, operator=actor_id))
            except Exception as exc:
                raise _model_error(exc) from exc

    def enable(self, asset_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                asset = self.lifecycle.assets.get(asset_id)
                if asset.status == "registered":
                    return self._project(asset)
                asset = self.lifecycle.enable_preparation_only(asset_id, operator=actor_id)
                _reset_simulation_catalog()
                return self._project(asset)
            except Exception as exc:
                raise _model_error(exc) from exc

    def disable(self, asset_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                asset = self.lifecycle.assets.get(asset_id)
                if asset.status in {"blocked", "archived"}:
                    return self._project(asset)
                if asset.status not in {"approved", "registered"}:
                    raise AdminAPIError("MODEL_DISABLE_NOT_ALLOWED", "Only approved or registered assets can be disabled.", status_code=409)
                asset = self.lifecycle.block(asset_id, actor_type="operator")
                _reset_simulation_catalog()
                return self._project(asset)
            except AdminAPIError:
                raise
            except Exception as exc:
                raise _model_error(exc) from exc

    def smoke(self, asset_id: str, *, real_resource_opt_in: bool = False) -> dict[str, Any]:
        self.lifecycle.assets.get(asset_id)
        raise AdminAPIError(
            "MODEL_SMOKE_REQUIRES_INFRASTRUCTURE",
            "Uploaded file models are not execution-certified and cannot use the MATLAB dispatcher.",
            status_code=503,
            details={"real_resource_opt_in": bool(real_resource_opt_in), "execution_allowed": False},
        )

    def rollback(self, asset_id: str, *, target_version: str) -> dict[str, Any]:
        self.lifecycle.assets.get(asset_id)
        raise AdminAPIError(
            "MODEL_ROLLBACK_REQUIRES_INFRASTRUCTURE",
            "Custom model activation and rollback require a reviewed execution-certification seam.",
            status_code=503,
            details={"target_version": str(target_version), "production_allowlist_modified": False},
        )

    def version_history(self, model_id: str | None) -> dict[str, Any]:
        if not model_id:
            return {"items": [], "total": 0}
        items = [self._project(asset) for asset in self.lifecycle.assets.list() if (asset.metadata.get("manifest") or {}).get("model_id") == model_id]
        items.sort(key=lambda item: str(item.get("version") or ""), reverse=True)
        return {"items": items, "total": len(items), "immutable_versions": True}

    @staticmethod
    def _project(asset: Any) -> dict[str, Any]:
        raw = admin_asset_payload(asset)
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        manifest = metadata.get("manifest") if isinstance(metadata.get("manifest"), dict) else {}
        validation = metadata.get("validation") if isinstance(metadata.get("validation"), dict) else {}
        raw_status = str(raw.get("status") or "unknown")
        status = {
            "quarantined": "validation_failed" if metadata.get("validation_status") == "validation_failed" else "uploaded",
            "pending_review": "pending_approval",
            "approved": "approved_file_only",
            "registered": "preparation_only",
            "blocked": "disabled",
            "archived": "disabled",
        }.get(raw_status, raw_status)
        return {
            "asset_id": raw.get("asset_id"),
            "model_id": manifest.get("model_id") or raw.get("proposed_model_id") or raw.get("registered_model_id"),
            "version": manifest.get("version"),
            "display_name": manifest.get("display_name") or raw.get("original_filename"),
            "description": manifest.get("description"),
            "filename": raw.get("original_filename"),
            "backend": manifest.get("backend"),
            "entry_point": manifest.get("entry_point"),
            "execution_type": manifest.get("execution_type"),
            "status": status,
            "lifecycle_status": raw_status,
            "sha256": raw.get("sha256"),
            "size_bytes": raw.get("size_bytes"),
            "manifest": manifest,
            "validation": validation,
            "security_scan": raw.get("security_scan_status"),
            "allowlist": False,
            "execution_allowed": False,
            "human_validated": False,
            "smoke": "not_available",
            "uploaded_at": raw.get("uploaded_at"),
            "updated_at": raw.get("updated_at"),
            "approved_at": raw.get("approved_at"),
            "limitations": ["Uploaded custom models are not execution-certified and cannot enter the MATLAB dispatcher allowlist."],
        }


def _model_error(exc: Exception) -> AdminAPIError:
    code = str(getattr(exc, "code", "MODEL_ASSET_OPERATION_FAILED")).upper()
    status_code = int(getattr(exc, "status_code", 400) or 400)
    return AdminAPIError(code, str(exc), status_code=status_code)


def _reset_simulation_catalog() -> None:
    try:
        from services.simulation_service.catalog import reset_catalog_service

        reset_catalog_service()
    except ImportError:
        return


_DEFAULT_MODEL_SERVICE: ModelAdminService | None = None


def get_model_admin_service() -> ModelAdminService:
    global _DEFAULT_MODEL_SERVICE
    if _DEFAULT_MODEL_SERVICE is None:
        _DEFAULT_MODEL_SERVICE = ModelAdminService()
    return _DEFAULT_MODEL_SERVICE


__all__ = [
    "MatlabStaticSafetyScanner",
    "MatlabModelContractValidator",
    "ModelAdminService",
    "ModelManifestValidator",
    "get_model_admin_service",
    "manifest_identity",
]
