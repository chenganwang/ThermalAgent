from __future__ import annotations

from typing import Any, Callable

from services.ingest_service.knowledge.corrections import (
    KnowledgeChunkCorrectionService,
    KnowledgeCorrectionError,
)

from ..contracts import AdminAPIError


class KnowledgeCorrectionAdminService:
    """Admin error-contract adapter over canonical ingestion corrections."""

    def __init__(self, service: KnowledgeChunkCorrectionService) -> None:
        self.service = service

    def _call(self, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except KnowledgeCorrectionError as exc:
            raise AdminAPIError(exc.code, exc.message, status_code=exc.status_code) from exc

    def get_chunk(self, document_id: int, chunk_id: int) -> dict[str, Any]:
        return self._call(lambda: self.service.get_chunk(document_id, chunk_id))

    def revise_chunk(self, document_id: int, chunk_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._call(lambda: self.service.revise_chunk(document_id, chunk_id, **kwargs))

    def restore_revision(self, document_id: int, chunk_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._call(lambda: self.service.restore_revision(document_id, chunk_id, **kwargs))

    def restore_original(self, document_id: int, chunk_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._call(lambda: self.service.restore_original(document_id, chunk_id, **kwargs))


__all__ = ["KnowledgeCorrectionAdminService"]
