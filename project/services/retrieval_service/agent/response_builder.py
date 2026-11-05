from __future__ import annotations

from typing import Any

from services.data_asset_service import ProjectionLevel, project_retrieval_source

from .contracts import AgentResponse
from .metadata_builder import ensure_metadata_contract
from .state import AgentContext


def build_agent_response(
    context: AgentContext | None = None,
    *,
    answer_text: str | None = None,
    query: str | None = None,
    task_type: str | None = None,
    retrieval_count: int | None = None,
    task: dict[str, Any] | None = None,
    rewrite: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable ThermalAgent answer response.

    This is the single place that defines the public top-level response shape
    for ThermalAgent.answer() and FastAPI /agent/answer.
    """

    if context is not None:
        task_data = dict(context.task or {})
        source_values = [
            project_retrieval_source(source, ProjectionLevel.LLM_SAFE)
            for source in list(context.sources or [])
            if isinstance(source, dict)
        ]
        return AgentResponse(
            answer=str(context.answer or ""),
            query=str(context.request.query or ""),
            task_type=str(task_data.get("task_type") or "unknown"),
            retrieval_count=len(source_values),
            task=task_data,
            rewrite=dict(context.rewrite or {}),
            sources=source_values,
            session_id=context.request.session_id,
            metadata=ensure_metadata_contract(context.metadata),
        ).to_dict()

    source_values = [
        project_retrieval_source(source, ProjectionLevel.LLM_SAFE)
        for source in list(sources or [])
        if isinstance(source, dict)
    ]
    return AgentResponse(
        answer=str(answer_text or ""),
        query=str(query or ""),
        task_type=str(task_type or "unknown"),
        retrieval_count=len(source_values),
        task=dict(task or {}),
        rewrite=dict(rewrite or {}),
        sources=source_values,
        session_id=session_id or "default",
        metadata=ensure_metadata_contract(metadata),
    ).to_dict()


__all__ = ["build_agent_response"]
