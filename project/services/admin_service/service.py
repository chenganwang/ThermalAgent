from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request

from services.retrieval_service.config import load_config

from .audit_adapter import LegacyAuditAdapter
from .checkers import utc_now_iso
from .contracts import AdminCheckContext, ModuleHealth
from .registry import ModuleRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AdminReadService:
    def __init__(
        self,
        *,
        registry: ModuleRegistry | None = None,
        audit: LegacyAuditAdapter | None = None,
    ) -> None:
        self.registry = registry or ModuleRegistry()
        self.audit = audit or LegacyAuditAdapter(PROJECT_ROOT)

    def context(self, request: Request) -> AdminCheckContext:
        cfg = getattr(request.app.state, "cfg", None)
        if cfg is None:
            cfg = load_config(project_root=PROJECT_ROOT)
        return AdminCheckContext(app=request.app, cfg=cfg, project_root=PROJECT_ROOT)

    def list_modules(
        self,
        request: Request,
        *,
        category: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        items = self.registry.list_health(self.context(request), force=False)
        if category:
            items = [item for item in items if item.category == category]
        if status:
            items = [item for item in items if item.status == status]
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "summary": self.registry.summarize(items),
            "generated_at": utc_now_iso(),
            "read_only": True,
        }

    def get_module(self, request: Request, module_id: str) -> dict[str, Any]:
        item = self.registry.check(module_id, self.context(request), force=False)
        return item.model_dump(mode="json")

    def check_module(self, request: Request, module_id: str) -> dict[str, Any]:
        item = self.registry.check(module_id, self.context(request), force=True)
        return {
            "module": item.model_dump(mode="json"),
            "side_effects": [],
            "check_mode": "bounded_read_only",
        }

    def check_all(self, request: Request) -> dict[str, Any]:
        items = self.registry.list_health(self.context(request), force=True)
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "summary": self.registry.summarize(items),
            "side_effects": [],
            "check_mode": "bounded_read_only",
            "generated_at": utc_now_iso(),
        }

    def overview(self, request: Request) -> dict[str, Any]:
        items = self.registry.list_health(self.context(request), force=False)
        summary = self.registry.summarize(items)
        recent_audit = self.audit.list_events(limit=5)
        by_id = {item.module_id: item for item in items}
        model_assets = by_id.get("model_assets")
        pending_reviews = 0
        if model_assets is not None:
            pending_reviews = int(model_assets.metrics.get("pending_review_count") or 0)
        recent_errors = [
            {
                "module_id": item.module_id,
                "error_code": item.error_code,
                "message": item.message,
                "observed_at": item.observed_at,
            }
            for item in items
            if item.error_code
        ][:10]
        return {
            "overall_status": summary["overall_status"],
            "module_counts": summary["counts"],
            "module_total": summary["total"],
            "modules": [item.model_dump(mode="json") for item in items],
            "active_jobs": 0,
            "job_system_enabled": False,
            "pending_reviews": pending_reviews,
            "recent_errors": recent_errors,
            "recent_audit": recent_audit["items"],
            "audit_partial": recent_audit["partial"],
            "storage": {
                "runtime": _module_summary(by_id.get("runtime_storage")),
                "evidence": _module_summary(by_id.get("evidence_storage")),
            },
            "generated_at": utc_now_iso(),
            "read_only": True,
            "side_effects": [],
        }


def _module_summary(item: ModuleHealth | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "module_id": item.module_id,
        "status": item.status,
        "severity": item.severity,
        "metrics": item.metrics,
        "observed_at": item.observed_at,
    }


_DEFAULT_ADMIN_SERVICE = AdminReadService()


def get_admin_read_service() -> AdminReadService:
    return _DEFAULT_ADMIN_SERVICE


__all__ = ["AdminReadService", "PROJECT_ROOT", "get_admin_read_service"]
