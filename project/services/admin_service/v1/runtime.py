from __future__ import annotations

import os
from pathlib import Path

from services.ingest_service.knowledge.correction_repository import MySQLChunkMutationStore
from services.ingest_service.knowledge.corrections import KnowledgeChunkCorrectionService
from services.ingest_service.knowledge.page_reparse import CanonicalPageParser
from services.retrieval_service.config import load_config
from services.simulation_service.modeling.generated_model_metadata import DEFAULT_EPHEMERAL_TTL_SECONDS
from services.simulation_service.modeling.janitor import GeneratedModelJanitor
from services.simulation_service.modeling.lifecycle import GeneratedModelService

from .corrections import KnowledgeCorrectionAdminService
from .reparse import CanonicalPageReparseAdapter, PageReparseAdminService, PageReparsePreviewStore
from .documents import DocumentAdminRepository
from .knowledge import CanonicalKnowledgeAdapter, KnowledgeAdminService, KnowledgeStagingStore
from .index_adapter import CanonicalKnowledgeIndexAdapter
from .index_sync import KnowledgeIndexStateStore, KnowledgeIndexSyncService
from .models import ModelAdminService
from .generated_models import GeneratedModelAdminService
from .operations import AdminAuditStore, AdminJobStore, GeneratedModelOperationRecorder


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def admin_runtime_root() -> Path:
    raw = os.getenv("ADMIN_CONSOLE_RUNTIME_ROOT", "").strip()
    if not raw:
        return (PROJECT_ROOT / "runtime" / "admin_console").resolve()
    path = Path(raw)
    resolved = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
    # Deployment may point to an external runtime volume, but source/model/data
    # directories are never accepted from a request.
    return resolved


_knowledge: tuple[Path, KnowledgeAdminService] | None = None
_documents: DocumentAdminRepository | None = None
_models: ModelAdminService | None = None
_generated_models: GeneratedModelAdminService | None = None
_generated_model_janitor: GeneratedModelJanitor | None = None
_jobs: tuple[Path, AdminJobStore] | None = None
_audit: tuple[Path, AdminAuditStore] | None = None
_corrections: KnowledgeCorrectionAdminService | None = None
_reparse: tuple[Path, PageReparseAdminService] | None = None
_index_sync: tuple[Path, KnowledgeIndexSyncService] | None = None


def get_admin_v1_knowledge_service() -> KnowledgeAdminService:
    global _knowledge
    root = admin_runtime_root() / "knowledge"
    if _knowledge is None or _knowledge[0] != root:
        _knowledge = (root, KnowledgeAdminService(KnowledgeStagingStore(root), CanonicalKnowledgeAdapter(PROJECT_ROOT)))
    return _knowledge[1]


def get_document_admin_repository() -> DocumentAdminRepository:
    global _documents
    if _documents is None:
        _documents = DocumentAdminRepository(PROJECT_ROOT)
    return _documents


def get_admin_v1_model_service() -> ModelAdminService:
    global _models
    if _models is None:
        _models = ModelAdminService()
    return _models


def get_admin_generated_model_service() -> GeneratedModelAdminService:
    global _generated_models
    if _generated_models is None:
        raw_ttl = os.getenv("GENERATED_MODEL_EPHEMERAL_TTL_SECONDS", "").strip()
        try:
            ttl_seconds = max(1, int(raw_ttl)) if raw_ttl else DEFAULT_EPHEMERAL_TTL_SECONDS
        except ValueError:
            ttl_seconds = DEFAULT_EPHEMERAL_TTL_SECONDS
        _generated_models = GeneratedModelAdminService(
            lifecycle=GeneratedModelService(ephemeral_ttl_seconds=ttl_seconds),
        )
    return _generated_models


def get_generated_model_janitor() -> GeneratedModelJanitor:
    global _generated_model_janitor
    if _generated_model_janitor is None:
        lifecycle = get_admin_generated_model_service().lifecycle
        _generated_model_janitor = GeneratedModelJanitor(
            lifecycle,
            job_store=get_admin_job_store(),
            audit_store=get_admin_workflow_audit_store(),
        )
    return _generated_model_janitor


def get_admin_job_store() -> AdminJobStore:
    global _jobs
    root = admin_runtime_root() / "jobs"
    if _jobs is None or _jobs[0] != root:
        _jobs = (root, AdminJobStore(root))
    return _jobs[1]


def get_admin_workflow_audit_store() -> AdminAuditStore:
    global _audit
    path = admin_runtime_root() / "audit" / "admin_v1_audit.jsonl"
    if _audit is None or _audit[0] != path:
        _audit = (path, AdminAuditStore(path))
    return _audit[1]


def get_generated_model_operation_recorder() -> GeneratedModelOperationRecorder:
    return GeneratedModelOperationRecorder(
        get_admin_job_store(),
        get_admin_workflow_audit_store(),
    )


def get_admin_knowledge_correction_service() -> KnowledgeCorrectionAdminService:
    global _corrections
    if _corrections is None:
        store = MySQLChunkMutationStore(load_config(project_root=PROJECT_ROOT))
        _corrections = KnowledgeCorrectionAdminService(KnowledgeChunkCorrectionService(store))
    return _corrections


def get_admin_page_reparse_service() -> PageReparseAdminService:
    global _reparse
    root = admin_runtime_root() / "page_reparse"
    if _reparse is None or _reparse[0] != root:
        cfg = load_config(project_root=PROJECT_ROOT)
        chunks = MySQLChunkMutationStore(cfg)
        adapter = CanonicalPageReparseAdapter(
            get_document_admin_repository(),
            chunks,
            CanonicalPageParser(cfg),
        )
        _reparse = (root, PageReparseAdminService(PageReparsePreviewStore(root), adapter))
    return _reparse[1]


def get_admin_knowledge_index_sync_service() -> KnowledgeIndexSyncService:
    global _index_sync
    root = admin_runtime_root() / "index_sync"
    if _index_sync is None or _index_sync[0] != root:
        cfg = load_config(project_root=PROJECT_ROOT)
        adapter = CanonicalKnowledgeIndexAdapter(cfg, root / "candidates")
        _index_sync = (root, KnowledgeIndexSyncService(KnowledgeIndexStateStore(root / "state"), adapter))
    return _index_sync[1]


__all__ = [
    "admin_runtime_root",
    "get_admin_job_store",
    "get_admin_knowledge_correction_service",
    "get_admin_knowledge_index_sync_service",
    "get_admin_page_reparse_service",
    "get_admin_v1_knowledge_service",
    "get_admin_v1_model_service",
    "get_admin_generated_model_service",
    "get_generated_model_operation_recorder",
    "get_generated_model_janitor",
    "get_admin_workflow_audit_store",
    "get_document_admin_repository",
]
