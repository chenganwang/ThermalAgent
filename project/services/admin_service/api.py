from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import (
    AdminIdentity,
    require_admin_config_write_access,
    require_admin_read_access,
    require_admin_workflow_write_access,
)
from .actions.schemas import ActionRequest
from .actions.service import ActionService, get_action_service
from .checkers import utc_now_iso
from .config.schemas import ConfigPatchRequest, ConfigRollbackRequest
from .config.service import ConfigActor, ConfigRegistryService, get_config_registry_service
from .contracts import AdminAPIError, AdminError, AdminResponse
from .redaction import sanitize_admin_value
from .service import AdminReadService, get_admin_read_service
from .v1.documents import DocumentAdminRepository
from .v1.corrections import KnowledgeCorrectionAdminService
from .v1.knowledge import KnowledgeAdminService
from .v1.models import ModelAdminService
from .v1.generated_models import GeneratedModelAdminService
from .v1.experience import AdminTaskReader, get_admin_task_reader, knowledge_coverage
from .v1.operations import AdminAuditStore, AdminJobStore
from .v1.reparse import PageReparseAdminService
from .v1.index_sync import KnowledgeIndexSyncService
from .v1.runtime import (
    get_admin_job_store,
    get_admin_generated_model_service,
    get_admin_knowledge_correction_service,
    get_admin_knowledge_index_sync_service,
    get_admin_page_reparse_service,
    get_admin_v1_knowledge_service,
    get_admin_v1_model_service,
    get_admin_workflow_audit_store,
    get_generated_model_operation_recorder,
    get_generated_model_janitor,
    get_document_admin_repository,
)
from pydantic import BaseModel, ConfigDict, Field


ADMIN_API_PREFIX = "/admin/api/v1"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")

router = APIRouter(prefix=ADMIN_API_PREFIX, tags=["admin-control-center"])


class ModelApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    operator_notes: str = ""


class ModelRejectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class ModelSmokePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    real_resource_opt_in: bool = False


class ModelRollbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_version: str


class GeneratedModelApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class GeneratedModelMetadataPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class GeneratedModelEngineeringRevisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_ir: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)


class GeneratedModelDeletePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class StagedChunkEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_text: str = Field(min_length=1, max_length=1_000_000)
    reason: str = Field(default="", max_length=500)
    base_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=200)


class StagedChunkRestorePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=500)
    base_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=200)


class StagedChunkParticipationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class StagingWithdrawPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PersistedChunkRestorePayload(StagedChunkRestorePayload):
    revision_id: str = Field(min_length=1, max_length=120)


class PageReparsePreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_number: int = Field(ge=1)
    strategy: str = Field(default="standard_pdf_text", min_length=1, max_length=80)


class PageReparseApplyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200)


def _envelope(request: Request, data: Any, *, warnings: list[str] | None = None) -> dict[str, Any]:
    return AdminResponse(
        success=True,
        request_id=_request_id(request),
        data=sanitize_admin_value(data),
        error=None,
        warnings=list(warnings or []),
        timestamp=utc_now_iso(),
    ).model_dump(mode="json")


def _error_envelope(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    payload = AdminResponse(
        success=False,
        request_id=_request_id(request),
        data=None,
        error=AdminError(
            code=code,
            message=str(sanitize_admin_value(message)),
            details=sanitize_admin_value(details or {}),
            retryable=retryable,
        ),
        warnings=[],
        timestamp=utc_now_iso(),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


@router.get("/session", response_model=AdminResponse)
def admin_session(
    request: Request,
    identity: AdminIdentity = Depends(require_admin_read_access),
) -> dict[str, Any]:
    return _envelope(
        request,
        {
            "identity": identity.to_dict(),
            "phase": "C-1",
            "control_center": "ThermalAgent Control Center",
            "api_version": "v1",
        },
    )


@router.get("/config", response_model=AdminResponse)
def admin_config(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: ConfigRegistryService = Depends(get_config_registry_service),
) -> dict[str, Any]:
    return _envelope(request, service.read_config())


@router.get("/config/schema", response_model=AdminResponse)
def admin_config_schema(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: ConfigRegistryService = Depends(get_config_registry_service),
) -> dict[str, Any]:
    return _envelope(request, service.read_schema())


@router.get("/config/history", response_model=AdminResponse)
def admin_config_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=256),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: ConfigRegistryService = Depends(get_config_registry_service),
) -> dict[str, Any]:
    return _envelope(request, service.read_history(limit=limit, cursor=cursor))


@router.get("/actions", response_model=AdminResponse)
def admin_actions(
    request: Request,
    category: str | None = Query(default=None, max_length=64),
    risk_level: str | None = Query(default=None, max_length=32),
    enabled: bool | None = Query(default=None),
    available: bool | None = Query(default=None),
    identity: AdminIdentity = Depends(require_admin_read_access),
    service: ActionService = Depends(get_action_service),
) -> dict[str, Any]:
    return _envelope(
        request,
        service.list_actions(
            identity,
            category=category,
            risk_level=risk_level,
            enabled=enabled,
            available=available,
        ),
    )


@router.get("/actions/{action_id}", response_model=AdminResponse)
def admin_action_detail(
    action_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_read_access),
    service: ActionService = Depends(get_action_service),
) -> dict[str, Any]:
    return _envelope(request, service.get_action(identity, action_id))


@router.post("/actions/{action_id}/dry-run", response_model=AdminResponse)
def admin_action_dry_run(
    action_id: str,
    payload: ActionRequest,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_read_access),
    service: ActionService = Depends(get_action_service),
) -> dict[str, Any]:
    result = service.dry_run(identity, action_id, payload, request_id=_request_id(request))
    return _envelope(request, result, warnings=list(result.get("warnings") or []))


@router.post("/actions/{action_id}/invoke", response_model=AdminResponse)
def admin_action_invoke(
    action_id: str,
    payload: ActionRequest,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_read_access),
    service: ActionService = Depends(get_action_service),
) -> dict[str, Any]:
    result = service.invoke(identity, action_id, payload, request_id=_request_id(request))
    return _envelope(request, result, warnings=list(result.get("warnings") or []))


@router.patch("/config", response_model=AdminResponse)
def admin_config_patch(
    payload: ConfigPatchRequest,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_config_write_access),
    service: ConfigRegistryService = Depends(get_config_registry_service),
) -> dict[str, Any]:
    result = service.patch(
        payload,
        actor=_config_actor(identity),
        request_id=_request_id(request),
    )
    warnings = list(result.pop("warnings", []))
    return _envelope(request, result, warnings=warnings)


@router.post("/config/rollback", response_model=AdminResponse)
def admin_config_rollback(
    payload: ConfigRollbackRequest,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_config_write_access),
    service: ConfigRegistryService = Depends(get_config_registry_service),
) -> dict[str, Any]:
    result = service.rollback(
        payload,
        actor=_config_actor(identity),
        request_id=_request_id(request),
    )
    warnings = list(result.pop("warnings", []))
    return _envelope(request, result, warnings=warnings)


@router.get("/overview", response_model=AdminResponse)
def admin_overview(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    return _envelope(request, service.overview(request))


@router.get("/modules", response_model=AdminResponse)
def admin_modules(
    request: Request,
    category: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    return _envelope(request, service.list_modules(request, category=category, status=status))


@router.post("/modules/check-all", response_model=AdminResponse)
def admin_modules_check_all(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    return _envelope(request, service.check_all(request))


@router.get("/modules/{module_id}", response_model=AdminResponse)
def admin_module_detail(
    module_id: str,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    return _envelope(request, service.get_module(request, module_id))


@router.post("/modules/{module_id}/check", response_model=AdminResponse)
def admin_module_check(
    module_id: str,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    return _envelope(request, service.check_module(request, module_id))


@router.get("/audit", response_model=AdminResponse)
def admin_audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=256),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    return _envelope(request, service.audit.list_events(limit=limit, cursor=cursor))


@router.get("/audit/{audit_id}", response_model=AdminResponse)
def admin_audit_detail(
    audit_id: str,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    return _envelope(request, service.audit.get_event(audit_id))


# ---------------------------------------------------------------------------
# Admin Console V1.  These routes adapt existing ingestion/model services;
# they do not add a second writer, model runtime, or database schema.


@router.get("/dashboard", response_model=AdminResponse)
def admin_v1_dashboard(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    health: AdminReadService = Depends(get_admin_read_service),
    documents: DocumentAdminRepository = Depends(get_document_admin_repository),
    models: ModelAdminService = Depends(get_admin_v1_model_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    overview = health.overview(request)
    overview["readiness"] = _admin_readiness(overview.get("overall_status"))
    warnings: list[str] = []
    try:
        statistics = documents.statistics()
    except AdminAPIError as exc:
        statistics = {"documents": None, "chunks": None, "knowledge_units": None}
        warnings.append(exc.code)
    try:
        model_count = models.list_models()["total"]
    except AdminAPIError as exc:
        model_count = None
        warnings.append(exc.code)
    active_jobs = jobs.list(status="running", limit=100)
    return _envelope(
        request,
        {
            **overview,
            "statistics": {**statistics, "simulation_models": model_count},
            "active_jobs": active_jobs["total"],
            "job_system_enabled": True,
            "job_persistence": "host_local_file_backed",
            "durable_distributed_queue": False,
            "recent_admin_activity": audit.list(limit=8)["items"],
        },
        warnings=warnings,
    )


@router.get("/knowledge/coverage", response_model=AdminResponse)
def admin_knowledge_coverage(request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    documents: DocumentAdminRepository = Depends(get_document_admin_repository)) -> dict[str, Any]:
    return _envelope(request, knowledge_coverage(documents))


@router.get("/agent-tasks", response_model=AdminResponse)
def admin_agent_tasks(request: Request, limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    tasks: AdminTaskReader = Depends(get_admin_task_reader)) -> dict[str, Any]:
    return _envelope(request, tasks.read(limit=limit, offset=offset))


@router.get("/agent-tasks/{task_id}", response_model=AdminResponse)
def admin_agent_task(task_id: str, request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    tasks: AdminTaskReader = Depends(get_admin_task_reader)) -> dict[str, Any]:
    return _envelope(request, tasks.read(task_id))


@router.get("/knowledge/staging", response_model=AdminResponse)
def admin_v1_knowledge_staging(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
) -> dict[str, Any]:
    return _envelope(request, service.list_staging())


@router.post("/knowledge/staging/upload", response_model=AdminResponse)
async def admin_v1_knowledge_upload(
    request: Request,
    file: UploadFile = File(...),
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    content = await file.read()
    try:
        result = service.upload(
            filename=file.filename or "",
            content=content,
            mime_type=file.content_type,
            actor_id=identity.actor_id,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="UPLOAD_DOCUMENT", resource_type="document_upload",
            resource_id=str(file.filename or "upload")[:200], before=None, after=None, result="failed",
            error_code=exc.code, request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="UPLOAD_DOCUMENT", resource_type="document_staging",
        resource_id=str(result["staging_id"]), before=None, after=result, result="success", request_id=_request_id(request),
    )
    return _envelope(request, result)


def _run_knowledge_job(
    *,
    request: Request,
    identity: AdminIdentity,
    staging_id: str,
    job_type: str,
    action: str,
    operation: Any,
    jobs: AdminJobStore,
    audit: AdminAuditStore,
) -> dict[str, Any]:
    job = jobs.create(job_type=job_type, resource_type="document_staging", resource_id=staging_id, actor_id=identity.actor_id)
    jobs.start(job["job_id"], progress=10, message=f"{action} started")
    try:
        result = operation()
    except AdminAPIError as exc:
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        audit.append(
            actor_id=identity.actor_id, action=action, resource_type="document_staging", resource_id=staging_id,
            before=None, after=None, result="failed", error_code=exc.code, request_id=_request_id(request),
        )
        raise
    completed = jobs.succeed(job["job_id"], result={"resource_status": result.get("status")}, message=f"{action} completed")
    audit.append(
        actor_id=identity.actor_id, action=action, resource_type="document_staging", resource_id=staging_id,
        before=None, after=result, result="success", request_id=_request_id(request),
    )
    return {**result, "job": completed}


@router.post("/knowledge/staging/{staging_id}/preflight", response_model=AdminResponse)
def admin_v1_knowledge_preflight(
    staging_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_knowledge_job(
        request=request, identity=identity, staging_id=staging_id, job_type="document_preflight", action="DOCUMENT_PREFLIGHT",
        operation=lambda: service.preflight(staging_id, actor_id=identity.actor_id), jobs=jobs, audit=audit,
    )
    return _envelope(request, result)


@router.post("/knowledge/staging/{staging_id}/dry-run", response_model=AdminResponse)
def admin_v1_knowledge_dry_run(
    staging_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_knowledge_job(
        request=request, identity=identity, staging_id=staging_id, job_type="document_dry_run", action="DOCUMENT_DRY_RUN",
        operation=lambda: service.dry_run(staging_id, actor_id=identity.actor_id), jobs=jobs, audit=audit,
    )
    return _envelope(request, result)


@router.get("/knowledge/staging/{staging_id}/chunks", response_model=AdminResponse)
def admin_v1_staged_chunks(
    staging_id: str,
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    page_number: int | None = Query(default=None, ge=1),
    section: str | None = Query(default=None, max_length=200),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
) -> dict[str, Any]:
    return _envelope(request, service.list_staged_chunks(staging_id, query=query, page=page, page_size=page_size, page_number=page_number, section=section))


@router.get("/knowledge/staging/{staging_id}/chunks/{chunk_index}", response_model=AdminResponse)
def admin_v1_staged_chunk_detail(
    staging_id: str,
    chunk_index: int,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
) -> dict[str, Any]:
    return _envelope(request, service.get_staged_chunk(staging_id, chunk_index))


def _staged_edit_audit_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_index": result.get("chunk_index"),
        "version": result.get("version"),
        "edit_state": result.get("edit_state"),
        "length": result.get("length"),
    }


def _staged_participation_audit_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_index": result.get("chunk_index"),
        "participation_state": result.get("participation_state"),
        "included": result.get("included"),
    }


@router.put("/knowledge/staging/{staging_id}/chunks/{chunk_index}", response_model=AdminResponse)
def admin_v1_edit_staged_chunk(
    staging_id: str,
    chunk_index: int,
    payload: StagedChunkEditPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{staging_id}:{chunk_index}"
    try:
        result = service.edit_staged_chunk(
            staging_id,
            chunk_index,
            effective_text=payload.effective_text,
            reason=payload.reason,
            actor_id=identity.actor_id,
            base_version=payload.base_version,
            idempotency_key=payload.idempotency_key,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="EDIT_STAGED_CHUNK", resource_type="document_staging_chunk",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="EDIT_STAGED_CHUNK", resource_type="document_staging_chunk",
        resource_id=resource_id, before=None, after=_staged_edit_audit_payload(result), result="success",
        request_id=_request_id(request),
    )
    return _envelope(request, result)


@router.post("/knowledge/staging/{staging_id}/chunks/{chunk_index}/restore", response_model=AdminResponse)
def admin_v1_restore_staged_chunk(
    staging_id: str,
    chunk_index: int,
    payload: StagedChunkRestorePayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{staging_id}:{chunk_index}"
    try:
        result = service.restore_staged_chunk(
            staging_id,
            chunk_index,
            reason=payload.reason,
            actor_id=identity.actor_id,
            base_version=payload.base_version,
            idempotency_key=payload.idempotency_key,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="RESTORE_STAGED_CHUNK", resource_type="document_staging_chunk",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="RESTORE_STAGED_CHUNK", resource_type="document_staging_chunk",
        resource_id=resource_id, before=None, after=_staged_edit_audit_payload(result), result="success",
        request_id=_request_id(request),
    )
    return _envelope(request, result)


@router.post("/knowledge/staging/{staging_id}/chunks/{chunk_index}/exclude", response_model=AdminResponse)
def admin_v1_exclude_staged_chunk(
    staging_id: str,
    chunk_index: int,
    payload: StagedChunkParticipationPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{staging_id}:{chunk_index}"
    try:
        result = service.exclude_staged_chunk(
            staging_id,
            chunk_index,
            reason=payload.reason,
            actor_id=identity.actor_id,
            idempotency_key=payload.idempotency_key,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="EXCLUDE_STAGED_CHUNK", resource_type="document_staging_chunk",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="EXCLUDE_STAGED_CHUNK", resource_type="document_staging_chunk",
        resource_id=resource_id, before=None, after=_staged_participation_audit_payload(result), result="success",
        request_id=_request_id(request),
    )
    return _envelope(request, result)


@router.post("/knowledge/staging/{staging_id}/chunks/{chunk_index}/include", response_model=AdminResponse)
def admin_v1_include_staged_chunk(
    staging_id: str,
    chunk_index: int,
    payload: StagedChunkParticipationPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{staging_id}:{chunk_index}"
    try:
        result = service.restore_staged_chunk_inclusion(
            staging_id,
            chunk_index,
            reason=payload.reason,
            actor_id=identity.actor_id,
            idempotency_key=payload.idempotency_key,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="RESTORE_STAGED_CHUNK", resource_type="document_staging_chunk",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="RESTORE_STAGED_CHUNK", resource_type="document_staging_chunk",
        resource_id=resource_id, before=None, after=_staged_participation_audit_payload(result), result="success",
        request_id=_request_id(request),
    )
    return _envelope(request, result)


@router.post("/knowledge/staging/{staging_id}/commit", response_model=AdminResponse)
def admin_v1_knowledge_commit(
    staging_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_knowledge_job(
        request=request, identity=identity, staging_id=staging_id, job_type="document_commit", action="COMMIT_DOCUMENT",
        operation=lambda: service.commit(staging_id, actor_id=identity.actor_id), jobs=jobs, audit=audit,
    )
    return _envelope(request, result)


@router.post("/knowledge/staging/{staging_id}/withdraw", response_model=AdminResponse)
def admin_v1_knowledge_withdraw(
    staging_id: str,
    payload: StagingWithdrawPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    try:
        result = service.withdraw_staging(
            staging_id,
            reason=payload.reason,
            actor_id=identity.actor_id,
            idempotency_key=payload.idempotency_key,
        )
        cancelled_job_ids = jobs.cancel_active_for_resource(
            resource_type="document_staging",
            resource_id=staging_id,
            job_types=frozenset({"document_preflight", "document_dry_run"}),
            message="Staging workflow withdrawn",
        )
        result = {**result, "cancelled_job_ids": cancelled_job_ids}
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="WITHDRAW_STAGED_DOCUMENT", resource_type="document_staging",
            resource_id=staging_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="WITHDRAW_STAGED_DOCUMENT", resource_type="document_staging",
        resource_id=staging_id, before=None,
        after={
            "status": result.get("status"),
            "already_withdrawn": result.get("already_withdrawn"),
            "cleaned_resources": result.get("cleaned_resources"),
            "cancelled_job_count": len(cancelled_job_ids),
        },
        result="success", request_id=_request_id(request),
    )
    return _envelope(request, result)


@router.get("/knowledge/documents", response_model=AdminResponse)
def admin_v1_documents(
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, max_length=40),
    source_type: str | None = Query(default=None, max_length=80),
    sort: str = Query(default="created_desc", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    repository: DocumentAdminRepository = Depends(get_document_admin_repository),
) -> dict[str, Any]:
    return _envelope(request, repository.list_documents(query=query, status=status, source_type=source_type, sort=sort, page=page, page_size=page_size))


@router.get("/knowledge/documents/{document_id}", response_model=AdminResponse)
def admin_v1_document_detail(
    document_id: int,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    repository: DocumentAdminRepository = Depends(get_document_admin_repository),
    reparse: PageReparseAdminService = Depends(get_admin_page_reparse_service),
) -> dict[str, Any]:
    return _envelope(request, {**repository.get_document(document_id), "reparse": reparse.capabilities(document_id)})


@router.get("/knowledge/documents/{document_id}/chunks", response_model=AdminResponse)
def admin_v1_document_chunks(
    document_id: int,
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    page_number: int | None = Query(default=None, ge=1),
    section: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    repository: DocumentAdminRepository = Depends(get_document_admin_repository),
) -> dict[str, Any]:
    return _envelope(request, repository.list_chunks(document_id, query=query, page_number=page_number, section=section, page=page, page_size=page_size))


@router.get("/knowledge/documents/{document_id}/chunks/{chunk_id}", response_model=AdminResponse)
def admin_v1_document_chunk_detail(
    document_id: int,
    chunk_id: int,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    repository: DocumentAdminRepository = Depends(get_document_admin_repository),
    correction: KnowledgeCorrectionAdminService = Depends(get_admin_knowledge_correction_service),
) -> dict[str, Any]:
    return _envelope(request, {**repository.get_chunk(document_id, chunk_id), **correction.get_chunk(document_id, chunk_id)})


@router.put("/knowledge/documents/{document_id}/chunks/{chunk_id}", response_model=AdminResponse)
def admin_v1_edit_persisted_chunk(
    document_id: int,
    chunk_id: int,
    payload: StagedChunkEditPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    correction: KnowledgeCorrectionAdminService = Depends(get_admin_knowledge_correction_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{document_id}:{chunk_id}"
    try:
        result = correction.revise_chunk(
            document_id,
            chunk_id,
            effective_text=payload.effective_text,
            reason=payload.reason,
            actor_id=identity.actor_id,
            base_version=payload.base_version,
            idempotency_key=payload.idempotency_key,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="EDIT_KNOWLEDGE_CHUNK", resource_type="knowledge_chunk",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="EDIT_KNOWLEDGE_CHUNK", resource_type="knowledge_chunk",
        resource_id=resource_id, before=None, after=_staged_edit_audit_payload(result), result="success",
        request_id=_request_id(request),
    )
    pending_job = None
    if result.get("index_status") == "stale":
        pending_job = jobs.create(job_type="chunk_revision_index_update", resource_type="knowledge_chunk", resource_id=resource_id, actor_id=identity.actor_id)
    return _envelope(request, {**result, "index_job": pending_job})


@router.post("/knowledge/documents/{document_id}/chunks/{chunk_id}/restore", response_model=AdminResponse)
def admin_v1_restore_persisted_chunk(
    document_id: int,
    chunk_id: int,
    payload: PersistedChunkRestorePayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    correction: KnowledgeCorrectionAdminService = Depends(get_admin_knowledge_correction_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{document_id}:{chunk_id}"
    try:
        result = correction.restore_revision(
            document_id,
            chunk_id,
            revision_id=payload.revision_id,
            reason=payload.reason,
            actor_id=identity.actor_id,
            base_version=payload.base_version,
            idempotency_key=payload.idempotency_key,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="RESTORE_KNOWLEDGE_CHUNK", resource_type="knowledge_chunk",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="RESTORE_KNOWLEDGE_CHUNK", resource_type="knowledge_chunk",
        resource_id=resource_id, before=None, after=_staged_edit_audit_payload(result), result="success",
        request_id=_request_id(request),
    )
    pending_job = None
    if result.get("index_status") == "stale":
        pending_job = jobs.create(job_type="chunk_revision_index_update", resource_type="knowledge_chunk", resource_id=resource_id, actor_id=identity.actor_id)
    return _envelope(request, {**result, "index_job": pending_job})


@router.post("/knowledge/documents/{document_id}/chunks/{chunk_id}/restore-original", response_model=AdminResponse)
def admin_v1_restore_persisted_chunk_original(
    document_id: int,
    chunk_id: int,
    payload: StagedChunkRestorePayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    correction: KnowledgeCorrectionAdminService = Depends(get_admin_knowledge_correction_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{document_id}:{chunk_id}"
    try:
        result = correction.restore_original(
            document_id,
            chunk_id,
            reason=payload.reason,
            actor_id=identity.actor_id,
            base_version=payload.base_version,
            idempotency_key=payload.idempotency_key,
        )
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="RESTORE_KNOWLEDGE_CHUNK_ORIGINAL", resource_type="knowledge_chunk",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="RESTORE_KNOWLEDGE_CHUNK_ORIGINAL", resource_type="knowledge_chunk",
        resource_id=resource_id, before=None, after=_staged_edit_audit_payload(result), result="success",
        request_id=_request_id(request),
    )
    pending_job = None
    if result.get("index_status") == "stale":
        pending_job = jobs.create(job_type="chunk_revision_index_update", resource_type="knowledge_chunk", resource_id=resource_id, actor_id=identity.actor_id)
    return _envelope(request, {**result, "index_job": pending_job})


@router.post("/knowledge/documents/{document_id}/reparse-previews", response_model=AdminResponse)
def admin_v1_create_page_reparse_preview(
    document_id: int,
    payload: PageReparsePreviewPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    reparse: PageReparseAdminService = Depends(get_admin_page_reparse_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_id = f"{document_id}:{payload.page_number}"
    job = jobs.create(job_type="page_reparse", resource_type="document_page", resource_id=resource_id, actor_id=identity.actor_id)
    jobs.start(job["job_id"], progress=10, message="Page reparse preview started")
    try:
        result = reparse.create_preview(
            document_id=document_id,
            page_number=payload.page_number,
            strategy=payload.strategy,
            actor_id=identity.actor_id,
        )
    except AdminAPIError as exc:
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        audit.append(
            actor_id=identity.actor_id, action="REPARSE_PAGE_REQUEST", resource_type="document_page",
            resource_id=resource_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    completed = jobs.succeed(
        job["job_id"],
        result={"preview_id": result.get("preview_id"), "status": result.get("status")},
        message="Page reparse preview completed",
    )
    audit.append(
        actor_id=identity.actor_id, action="REPARSE_PAGE_REQUEST", resource_type="document_page",
        resource_id=resource_id, before=None,
        after={"preview_id": result.get("preview_id"), "status": result.get("status")},
        result="success", request_id=_request_id(request),
    )
    return _envelope(request, {**result, "job": completed})


@router.get("/knowledge/reparse-previews/{preview_id}", response_model=AdminResponse)
def admin_v1_page_reparse_preview(
    preview_id: str,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    reparse: PageReparseAdminService = Depends(get_admin_page_reparse_service),
) -> dict[str, Any]:
    return _envelope(request, reparse.get_preview(preview_id))


@router.post("/knowledge/reparse-previews/{preview_id}/apply", response_model=AdminResponse)
def admin_v1_apply_page_reparse_preview(
    preview_id: str,
    payload: PageReparseApplyPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    reparse: PageReparseAdminService = Depends(get_admin_page_reparse_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    try:
        result = reparse.apply_preview(preview_id, actor_id=identity.actor_id, idempotency_key=payload.idempotency_key)
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action="APPLY_REPARSE_RESULT", resource_type="page_reparse_preview",
            resource_id=preview_id, before=None, after=None, result="failed", error_code=exc.code,
            request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action="APPLY_REPARSE_RESULT", resource_type="page_reparse_preview",
        resource_id=preview_id, before=None,
        after={"status": result.get("status"), "index_status": (result.get("apply_result") or {}).get("index_status")},
        result="success", request_id=_request_id(request),
    )
    pending_job = None
    if (result.get("apply_result") or {}).get("index_status") == "stale":
        pending_job = jobs.create(
            job_type="document_index_update",
            resource_type="document",
            resource_id=str((result.get("apply_result") or {}).get("document_id") or ""),
            actor_id=identity.actor_id,
        )
    return _envelope(request, {**result, "index_job": pending_job})


@router.get("/knowledge/index-sync", response_model=AdminResponse)
def admin_v1_index_sync_status(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: KnowledgeIndexSyncService = Depends(get_admin_knowledge_index_sync_service),
) -> dict[str, Any]:
    return _envelope(request, service.status())


@router.post("/knowledge/index-sync/candidates", response_model=AdminResponse)
def admin_v1_build_index_candidate(
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeIndexSyncService = Depends(get_admin_knowledge_index_sync_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    try:
        result = service.build_candidate(actor_id=identity.actor_id)
    except AdminAPIError as exc:
        job = jobs.create(job_type="index_candidate_build", resource_type="knowledge_index", resource_id="candidate", actor_id=identity.actor_id)
        jobs.start(job["job_id"], progress=5, message="Index candidate build started")
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        audit.append(actor_id=identity.actor_id, action="BUILD_INDEX_CANDIDATE", resource_type="knowledge_index", resource_id="candidate", before=None, after=None, result="failed", error_code=exc.code, request_id=_request_id(request))
        raise
    completed = None
    if not result.get("idempotent"):
        job = jobs.create(job_type="index_candidate_build", resource_type="knowledge_index", resource_id=str(result.get("candidate_id") or "candidate"), actor_id=identity.actor_id)
        jobs.start(job["job_id"], progress=95, message="Index candidate artifacts built")
        completed = jobs.succeed(job["job_id"], result={"candidate_id": result.get("candidate_id"), "status": result.get("status")}, message="Index candidate build completed")
    if result.get("status") == "candidate_ready":
        for pending in jobs.list(limit=500).get("items") or []:
            if pending.get("status") == "queued" and pending.get("type") in {"chunk_revision_index_update", "document_index_update"}:
                jobs.succeed(pending["job_id"], result={"candidate_id": result.get("candidate_id"), "index_status": "candidate"}, message="Candidate index generated")
    audit.append(actor_id=identity.actor_id, action="BUILD_INDEX_CANDIDATE", resource_type="knowledge_index", resource_id=str(result.get("candidate_id") or "candidate"), before=None, after={"status": result.get("status"), "active_index_modified": result.get("active_index_modified")}, result="success", request_id=_request_id(request))
    return _envelope(request, {**result, "job": completed})


@router.post("/knowledge/index-sync/candidates/{candidate_id}/validate", response_model=AdminResponse)
def admin_v1_validate_index_candidate(
    candidate_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeIndexSyncService = Depends(get_admin_knowledge_index_sync_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    job = jobs.create(job_type="index_validation", resource_type="knowledge_index_candidate", resource_id=candidate_id, actor_id=identity.actor_id)
    jobs.start(job["job_id"], progress=10, message="Index candidate validation started")
    try:
        result = service.validate_candidate(candidate_id, actor_id=identity.actor_id)
    except AdminAPIError as exc:
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        audit.append(actor_id=identity.actor_id, action="VALIDATE_INDEX_CANDIDATE", resource_type="knowledge_index_candidate", resource_id=candidate_id, before=None, after=None, result="failed", error_code=exc.code, request_id=_request_id(request))
        raise
    completed = jobs.succeed(job["job_id"], result={"candidate_id": candidate_id, "status": result.get("status")}, message="Index candidate validation completed")
    audit.append(actor_id=identity.actor_id, action="VALIDATE_INDEX_CANDIDATE", resource_type="knowledge_index_candidate", resource_id=candidate_id, before=None, after={"status": result.get("status")}, result="success", request_id=_request_id(request))
    return _envelope(request, {**result, "job": completed})


@router.post("/knowledge/index-sync/candidates/{candidate_id}/release", response_model=AdminResponse)
def admin_v1_release_index_candidate(
    candidate_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: KnowledgeIndexSyncService = Depends(get_admin_knowledge_index_sync_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    try:
        result = service.release_candidate(candidate_id, actor_id=identity.actor_id)
    except AdminAPIError as exc:
        job = jobs.create(job_type="index_release", resource_type="knowledge_index_candidate", resource_id=candidate_id, actor_id=identity.actor_id)
        jobs.start(job["job_id"], progress=10, message="Index candidate release started")
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        audit.append(actor_id=identity.actor_id, action="RELEASE_INDEX", resource_type="knowledge_index_candidate", resource_id=candidate_id, before=None, after=None, result="failed", error_code=exc.code, request_id=_request_id(request))
        raise
    error_code = str(result.get("error_code") or "") or None
    completed = None
    if not result.get("idempotent"):
        job = jobs.create(job_type="index_release", resource_type="knowledge_index_candidate", resource_id=candidate_id, actor_id=identity.actor_id)
        jobs.start(job["job_id"], progress=90, message="Index release gate evaluated")
        completed = jobs.succeed(job["job_id"], result={"candidate_id": candidate_id, "status": result.get("status")}, message="Index candidate released") if result.get("status") == "synced" else jobs.fail(job["job_id"], error_code=error_code or "INDEX_RELEASE_NOT_ACTIVE", message="Index candidate was not activated")
    audit.append(actor_id=identity.actor_id, action="RELEASE_INDEX", resource_type="knowledge_index_candidate", resource_id=candidate_id, before=None, after={"status": result.get("status"), "active_index_modified": bool((result.get("release") or {}).get("active_index_modified"))}, result="success" if result.get("status") == "synced" else "failed", error_code=error_code, request_id=_request_id(request))
    return _envelope(request, {**result, "job": completed})


@router.get("/knowledge/documents/{document_id}/content")
def admin_v1_document_content(
    document_id: int,
    request: Request,
    download: bool = Query(default=False),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    repository: DocumentAdminRepository = Depends(get_document_admin_repository),
) -> FileResponse:
    unknown_query = sorted(set(request.query_params) - {"download"})
    if unknown_query:
        raise AdminAPIError(
            "DOCUMENT_CONTENT_QUERY_INVALID",
            "Document content is resolved only by document id.",
            status_code=422,
            details={"unknown_fields": unknown_query},
        )
    resource = repository.resolve_content(document_id)
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path=resource.path,
        media_type=resource.media_type,
        filename=resource.filename,
        content_disposition_type=disposition,
    )


@router.get("/knowledge/units", response_model=AdminResponse)
def admin_v1_knowledge_units(
    request: Request,
    status: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    repository: DocumentAdminRepository = Depends(get_document_admin_repository),
) -> dict[str, Any]:
    return _envelope(request, repository.list_knowledge_units(status=status, page=page, page_size=page_size))


@router.get("/simulation-models", response_model=AdminResponse)
def admin_v1_simulation_models(
    request: Request,
    status: str | None = Query(default=None, max_length=40),
    query: str | None = Query(default=None, max_length=200),
    backend: str | None = Query(default=None, max_length=40),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
) -> dict[str, Any]:
    return _envelope(request, service.list_models(status=status, query=query, backend=backend))


@router.get("/generated-models", response_model=AdminResponse)
def admin_v1_generated_models(
    request: Request,
    status: str | None = Query(default=None, max_length=40),
    query: str | None = Query(default=None, max_length=200),
    origin: str | None = Query(default=None, max_length=40),
    retention: str | None = Query(default=None, max_length=40),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
) -> dict[str, Any]:
    return _envelope(request, service.list_models(status=status, query=query, origin=origin, retention=retention))


@router.get("/generated-models/{generation_id}", response_model=AdminResponse)
def admin_v1_generated_model_detail(
    generation_id: str,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
) -> dict[str, Any]:
    return _envelope(request, service.get_model(generation_id))


def _run_generated_model_audited(
    *,
    request: Request,
    identity: AdminIdentity,
    generation_id: str,
    action: str,
    operation: Any,
    audit: AdminAuditStore,
) -> dict[str, Any]:
    try:
        result = operation()
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action=action, resource_type="generated_model", resource_id=generation_id,
            before=None, after=None, result="failed", error_code=exc.code, request_id=_request_id(request),
        )
        raise
    summary = {
        "generation_id": result.get("generation_id"), "revision": result.get("revision"),
        "status": result.get("status"), "artifact_id": result.get("artifact_id"),
        "execution_eligible": result.get("execution_eligible"),
        "display_name": result.get("display_name"), "origin": result.get("origin"),
        "retention": result.get("retention"), "deleted": result.get("deleted"),
        "idempotent": result.get("idempotent"),
    }
    audit.append(
        actor_id=identity.actor_id, action=action, resource_type="generated_model", resource_id=generation_id,
        before=None, after=summary, result="success", request_id=_request_id(request),
    )
    return result


@router.patch("/generated-models/{generation_id}/metadata", response_model=AdminResponse)
def admin_v1_generated_model_metadata(
    generation_id: str,
    payload: GeneratedModelMetadataPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id,
        action="EDIT_GENERATED_MODEL_METADATA", audit=audit,
        operation=lambda: service.update_metadata(
            generation_id, actor_id=identity.actor_id,
            display_name=payload.display_name, description=payload.description,
        ),
    )
    return _envelope(request, result)


@router.post("/generated-models/{generation_id}/revisions", response_model=AdminResponse)
def admin_v1_generated_model_revision(
    generation_id: str,
    payload: GeneratedModelEngineeringRevisionPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id,
        action="CREATE_GENERATED_MODEL_REVISION", audit=audit,
        operation=lambda: service.create_engineering_revision(
            generation_id, actor_id=identity.actor_id, model_ir=payload.model_ir, reason=payload.reason,
        ),
    )
    return _envelope(request, result)


@router.post("/generated-models/{generation_id}/promote", response_model=AdminResponse)
def admin_v1_generated_model_promote(
    generation_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id,
        action="PROMOTE_GENERATED_MODEL_TO_RESIDENT", audit=audit,
        operation=lambda: service.promote(generation_id, actor_id=identity.actor_id),
    )
    return _envelope(request, result)


@router.delete("/generated-models/{generation_id}", response_model=AdminResponse)
def admin_v1_generated_model_delete(
    generation_id: str,
    payload: GeneratedModelDeletePayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    active_jobs = any(
        item.get("resource_type") == "generated_model"
        and item.get("resource_id") == generation_id
        and item.get("status") in {"queued", "running"}
        for item in jobs.list(limit=500).get("items", [])
    )
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id,
        action="DELETE_SIMULATION_MODEL", audit=audit,
        operation=lambda: service.delete(
            generation_id, actor_id=identity.actor_id, reason=payload.reason, active_jobs=active_jobs,
        ),
    )
    return _envelope(request, result)


@router.get("/generated-models-gc/preview", response_model=AdminResponse)
def admin_v1_generated_model_gc_preview(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    janitor: Any = Depends(get_generated_model_janitor),
) -> dict[str, Any]:
    return _envelope(request, janitor.sweep(dry_run=True))


@router.post("/generated-models-gc/run", response_model=AdminResponse)
def admin_v1_generated_model_gc_run(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    janitor: Any = Depends(get_generated_model_janitor),
) -> dict[str, Any]:
    return _envelope(request, janitor.sweep(dry_run=False))


@router.post("/generated-models/{generation_id}/compile", response_model=AdminResponse)
def admin_v1_generated_model_compile(
    generation_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
    operation_recorder: Any = Depends(get_generated_model_operation_recorder),
) -> dict[str, Any]:
    job = jobs.create(
        job_type="generated_model_compile", resource_type="generated_model",
        resource_id=generation_id, actor_id=identity.actor_id,
    )
    jobs.start(job["job_id"], progress=5, message="Compiling validated generated model")
    try:
        result = _run_generated_model_audited(
            request=request, identity=identity, generation_id=generation_id, action="COMPILE_GENERATED_MODEL",
            operation=lambda: service.compile(generation_id, actor_id=identity.actor_id), audit=audit,
        )
    except AdminAPIError as exc:
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        raise
    completed_job = jobs.succeed(
        job["job_id"],
        result={"generation_id": generation_id, "revision": result.get("revision"), "status": result.get("status")},
        message="Generated model compiled and queued for approval",
    )
    warnings: list[str] = []
    try:
        model_ir = result.get("model_ir") if isinstance(result.get("model_ir"), dict) else {}
        operation_recorder.record(
            "INSTRUMENT_GENERATED_MODEL",
            generation_id,
            status="success",
            summary={
                "artifact_id": result.get("artifact_id"),
                "model_ir_hash": result.get("model_ir_hash"),
                "output_count": len(model_ir.get("requested_outputs") or []),
                "status": result.get("status"),
            },
        )
    except Exception:
        warnings.append("GENERATED_MODEL_OPERATION_AUDIT_UNAVAILABLE")
    return _envelope(request, {**result, "job": completed_job}, warnings=warnings)


@router.post("/generated-models/{generation_id}/approve", response_model=AdminResponse)
def admin_v1_generated_model_approve(
    generation_id: str,
    payload: GeneratedModelApprovalPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id, action="APPROVE_GENERATED_MODEL", audit=audit,
        operation=lambda: service.approve(generation_id, actor_id=identity.actor_id, reason=payload.reason),
    )
    return _envelope(request, result)


@router.post("/generated-models/{generation_id}/reject", response_model=AdminResponse)
def admin_v1_generated_model_reject(
    generation_id: str,
    payload: ModelRejectPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id, action="REJECT_GENERATED_MODEL", audit=audit,
        operation=lambda: service.reject(generation_id, actor_id=identity.actor_id, reason=payload.reason),
    )
    return _envelope(request, result)


@router.post("/generated-models/{generation_id}/enable", response_model=AdminResponse)
def admin_v1_generated_model_enable(
    generation_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id, action="ENABLE_GENERATED_MODEL", audit=audit,
        operation=lambda: service.enable(generation_id, actor_id=identity.actor_id),
    )
    return _envelope(request, result)


@router.post("/generated-models/{generation_id}/disable", response_model=AdminResponse)
def admin_v1_generated_model_disable(
    generation_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: GeneratedModelAdminService = Depends(get_admin_generated_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_generated_model_audited(
        request=request, identity=identity, generation_id=generation_id, action="DISABLE_GENERATED_MODEL", audit=audit,
        operation=lambda: service.disable(generation_id, actor_id=identity.actor_id),
    )
    return _envelope(request, result)


@router.post("/simulation-models/upload", response_model=AdminResponse)
async def admin_v1_simulation_model_upload(
    request: Request,
    file: UploadFile = File(...),
    manifest: str = Form(...),
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    resource_hint = str(file.filename or "model-upload")[:200]
    try:
        manifest_payload = json.loads(manifest)
    except (json.JSONDecodeError, TypeError) as exc:
        audit.append(
            actor_id=identity.actor_id, action="UPLOAD_MODEL", resource_type="model_upload",
            resource_id=resource_hint, before=None, after=None, result="failed",
            error_code="MODEL_MANIFEST_INVALID", request_id=_request_id(request),
        )
        raise AdminAPIError("MODEL_MANIFEST_INVALID", "Model manifest must be valid JSON.", status_code=422) from exc
    if not isinstance(manifest_payload, dict):
        audit.append(
            actor_id=identity.actor_id, action="UPLOAD_MODEL", resource_type="model_upload",
            resource_id=resource_hint, before=None, after=None, result="failed",
            error_code="MODEL_MANIFEST_INVALID", request_id=_request_id(request),
        )
        raise AdminAPIError("MODEL_MANIFEST_INVALID", "Model manifest must be a JSON object.", status_code=422)
    job = jobs.create(job_type="model_validation", resource_type="model_upload", resource_id=file.filename or "model", actor_id=identity.actor_id)
    jobs.start(job["job_id"], progress=10, message="Validating model package")
    try:
        result = service.upload_and_validate(
            filename=file.filename or "", content=await file.read(), mime_type=file.content_type,
            manifest=manifest_payload, actor_id=identity.actor_id,
        )
    except AdminAPIError as exc:
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        audit.append(
            actor_id=identity.actor_id, action="UPLOAD_MODEL", resource_type="model_upload",
            resource_id=resource_hint, before=None, after=None, result="failed",
            error_code=exc.code, request_id=_request_id(request),
        )
        raise
    jobs.succeed(job["job_id"], result={"asset_id": result.get("asset_id"), "status": result.get("status")}, message="Model validation completed")
    audit.append(
        actor_id=identity.actor_id, action="UPLOAD_MODEL", resource_type="model_asset", resource_id=str(result["asset_id"]),
        before=None, after=result, result="success", request_id=_request_id(request),
    )
    return _envelope(request, result)


def _run_model_audited(
    *,
    request: Request,
    identity: AdminIdentity,
    asset_id: str,
    action: str,
    operation: Any,
    audit: AdminAuditStore,
) -> dict[str, Any]:
    try:
        result = operation()
    except AdminAPIError as exc:
        audit.append(
            actor_id=identity.actor_id, action=action, resource_type="model_asset", resource_id=asset_id,
            before=None, after=None, result="failed", error_code=exc.code, request_id=_request_id(request),
        )
        raise
    audit.append(
        actor_id=identity.actor_id, action=action, resource_type="model_asset", resource_id=asset_id,
        before=None, after=result, result="success", request_id=_request_id(request),
    )
    return result


@router.get("/simulation-models/{asset_id}", response_model=AdminResponse)
def admin_v1_simulation_model_detail(
    asset_id: str,
    request: Request,
    include_code: bool = Query(default=False),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
) -> dict[str, Any]:
    return _envelope(request, service.get_model(asset_id, include_code=include_code))


@router.post("/simulation-models/{asset_id}/approve", response_model=AdminResponse)
def admin_v1_simulation_model_approve(
    asset_id: str,
    payload: ModelApprovalPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_model_audited(
        request=request, identity=identity, asset_id=asset_id, action="APPROVE_MODEL", audit=audit,
        operation=lambda: service.approve(asset_id, scenario_id=payload.scenario_id, operator_notes=payload.operator_notes, actor_id=identity.actor_id),
    )
    return _envelope(request, result)


@router.post("/simulation-models/{asset_id}/reject", response_model=AdminResponse)
def admin_v1_simulation_model_reject(
    asset_id: str,
    payload: ModelRejectPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_model_audited(
        request=request, identity=identity, asset_id=asset_id, action="REJECT_MODEL", audit=audit,
        operation=lambda: service.reject(asset_id, reason=payload.reason, actor_id=identity.actor_id),
    )
    return _envelope(request, result)


@router.post("/simulation-models/{asset_id}/enable", response_model=AdminResponse)
def admin_v1_simulation_model_enable(
    asset_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_model_audited(
        request=request, identity=identity, asset_id=asset_id, action="ENABLE_MODEL", audit=audit,
        operation=lambda: service.enable(asset_id, actor_id=identity.actor_id),
    )
    return _envelope(request, result)


@router.post("/simulation-models/{asset_id}/disable", response_model=AdminResponse)
def admin_v1_simulation_model_disable(
    asset_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_model_audited(
        request=request, identity=identity, asset_id=asset_id, action="DISABLE_MODEL", audit=audit,
        operation=lambda: service.disable(asset_id, actor_id=identity.actor_id),
    )
    return _envelope(request, result)


@router.post("/simulation-models/{asset_id}/smoke", response_model=AdminResponse)
def admin_v1_simulation_model_smoke(
    asset_id: str,
    payload: ModelSmokePayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    job = jobs.create(job_type="model_smoke", resource_type="model_asset", resource_id=asset_id, actor_id=identity.actor_id)
    jobs.start(job["job_id"], progress=5, message="Checking smoke eligibility")
    try:
        result = service.smoke(asset_id, real_resource_opt_in=payload.real_resource_opt_in)
    except AdminAPIError as exc:
        jobs.fail(job["job_id"], error_code=exc.code, message=exc.message)
        audit.append(
            actor_id=identity.actor_id, action="RUN_MODEL_SMOKE", resource_type="model_asset", resource_id=asset_id,
            before=None, after=None, result="failed", error_code=exc.code, request_id=_request_id(request),
        )
        raise
    completed = {**result, "job": jobs.succeed(job["job_id"], result=result)}
    audit.append(
        actor_id=identity.actor_id, action="RUN_MODEL_SMOKE", resource_type="model_asset", resource_id=asset_id,
        before=None, after=completed, result="success", request_id=_request_id(request),
    )
    return _envelope(request, completed)


@router.post("/simulation-models/{asset_id}/rollback", response_model=AdminResponse)
def admin_v1_simulation_model_rollback(
    asset_id: str,
    payload: ModelRollbackPayload,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    service: ModelAdminService = Depends(get_admin_v1_model_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    result = _run_model_audited(
        request=request, identity=identity, asset_id=asset_id, action="ROLLBACK_MODEL", audit=audit,
        operation=lambda: service.rollback(asset_id, target_version=payload.target_version),
    )
    return _envelope(request, result)


@router.get("/jobs", response_model=AdminResponse)
def admin_v1_jobs(
    request: Request,
    job_type: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    jobs: AdminJobStore = Depends(get_admin_job_store),
) -> dict[str, Any]:
    return _envelope(request, jobs.list(job_type=job_type, status=status, limit=limit))


@router.get("/jobs/{job_id}", response_model=AdminResponse)
def admin_v1_job_detail(
    job_id: str,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    jobs: AdminJobStore = Depends(get_admin_job_store),
) -> dict[str, Any]:
    return _envelope(request, jobs.get(job_id))


@router.post("/jobs/{job_id}/retry", response_model=AdminResponse)
def admin_v1_job_retry(
    job_id: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_workflow_write_access),
    jobs: AdminJobStore = Depends(get_admin_job_store),
    knowledge: KnowledgeAdminService = Depends(get_admin_v1_knowledge_service),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    original = jobs.get(job_id)
    if original.get("status") not in {"failed", "cancelled"}:
        raise AdminAPIError("JOB_RETRY_NOT_ALLOWED", "Only failed or cancelled jobs can be retried.", status_code=409)
    staging_id = str(original.get("resource_id") or "")
    operations = {
        "document_preflight": ("DOCUMENT_PREFLIGHT", lambda: knowledge.preflight(staging_id, actor_id=identity.actor_id)),
        "document_dry_run": ("DOCUMENT_DRY_RUN", lambda: knowledge.dry_run(staging_id, actor_id=identity.actor_id)),
        "document_commit": ("COMMIT_DOCUMENT", lambda: knowledge.commit(staging_id, actor_id=identity.actor_id)),
        "document_ingestion": ("COMMIT_DOCUMENT", lambda: knowledge.commit(staging_id, actor_id=identity.actor_id)),
    }
    operation = operations.get(str(original.get("type") or ""))
    if operation is None:
        raise AdminAPIError("JOB_RETRY_UNSAFE", "This job type cannot be safely reconstructed for retry.", status_code=409)
    action, callback = operation
    result = _run_knowledge_job(
        request=request, identity=identity, staging_id=staging_id, job_type=str(original["type"]),
        action=action, operation=callback, jobs=jobs, audit=audit,
    )
    return _envelope(request, {"retried_job_id": job_id, "result": result})


@router.get("/workflow-audit", response_model=AdminResponse)
def admin_v1_workflow_audit(
    request: Request,
    action: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    _identity: AdminIdentity = Depends(require_admin_read_access),
    audit: AdminAuditStore = Depends(get_admin_workflow_audit_store),
) -> dict[str, Any]:
    return _envelope(request, audit.list(limit=limit, action=action))


@router.get("/system", response_model=AdminResponse)
def admin_v1_system(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin_read_access),
    health: AdminReadService = Depends(get_admin_read_service),
) -> dict[str, Any]:
    modules = health.list_modules(request)
    return _envelope(request, {
        **modules,
        "readiness": _admin_readiness((modules.get("summary") or {}).get("overall_status")),
        "dangerous_operations": [],
        "sql_console": False,
        "shell_console": False,
        "python_console": False,
        "matlab_console": False,
        "index_activation": False,
    })


def _admin_readiness(overall_status: Any) -> str:
    status = str((overall_status or {}).get("status") if isinstance(overall_status, dict) else overall_status or "unknown")
    return {
        "healthy": "ready",
        "degraded": "degraded",
        "unhealthy": "not_ready",
    }.get(status, "unknown")


class AdminRequestIdMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = str(scope.get("path") or "")
        if scope.get("type") != "http" or not path.startswith(ADMIN_API_PREFIX):
            await self.app(scope, receive, send)
            return
        request_id = _request_id_from_scope(scope)
        scope.setdefault("state", {})["admin_request_id"] = request_id

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        await self.app(scope, receive, send_with_headers)


def install_admin_api(app: FastAPI) -> None:
    if getattr(app.state, "admin_phase_a_installed", False):
        return
    app.include_router(router)
    app.add_middleware(AdminRequestIdMiddleware)
    app.add_exception_handler(AdminAPIError, _admin_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.state.admin_phase_a_installed = True


async def _admin_error_handler(request: Request, exc: AdminAPIError) -> JSONResponse:
    return _error_envelope(
        request,
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        retryable=exc.retryable,
    )


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if not request.url.path.startswith(ADMIN_API_PREFIX):
        return await request_validation_exception_handler(request, exc)
    fields = [
        {
            "location": [str(item) for item in error.get("loc") or ()],
            "type": str(error.get("type") or "validation_error"),
            "message": str(error.get("msg") or "Invalid request value."),
        }
        for error in exc.errors()
    ]
    return _error_envelope(
        request,
        code="REQUEST_INVALID",
        message="Admin request validation failed.",
        status_code=422,
        details={"fields": fields},
    )


async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if not request.url.path.startswith(ADMIN_API_PREFIX):
        return await http_exception_handler(request, exc)
    code = {
        401: "AUTH_REQUIRED",
        403: "PERMISSION_DENIED",
        404: "RESOURCE_NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
    }.get(exc.status_code, "REQUEST_FAILED")
    return _error_envelope(
        request,
        code=code,
        message="The Admin API request could not be completed.",
        status_code=exc.status_code,
    )


def _request_id(request: Request) -> str:
    existing = getattr(request.state, "admin_request_id", "")
    if _REQUEST_ID_PATTERN.fullmatch(str(existing)):
        return str(existing)
    generated = f"req_{uuid4().hex}"
    request.state.admin_request_id = generated
    return generated


def _request_id_from_scope(scope: dict[str, Any]) -> str:
    for key, value in scope.get("headers") or ():
        if key.lower() == b"x-request-id":
            candidate = value.decode("ascii", errors="ignore").strip()
            if _REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
            break
    return f"req_{uuid4().hex}"


def _config_actor(identity: AdminIdentity) -> ConfigActor:
    return ConfigActor(
        actor_id=identity.actor_id,
        role=identity.role,
        auth_source=identity.auth_mode,
    )


__all__ = ["ADMIN_API_PREFIX", "install_admin_api", "router"]
