"""Compatibility wrapper for the v11 FastAPI entrypoint.

New code should import from services.retrieval_service.api.v11_api_server.
This module preserves the existing uvicorn path:
services.retrieval_service.v11_api_server:app
"""

from __future__ import annotations

import os

from .api.schemas import (
    AgentAnalyzeExportRequest,
    AgentAnalyzeRequest,
    AgentAnalyzeResponse,
    AgentAnswerRequest,
    AgentAnswerResponse,
    AgentMemoryResetRequest,
    HealthResponse,
    NeighborItem,
    OpenWebUIToolSpecResponse,
    RetrieveContextResponse,
    RetrieveHit,
    RetrieveRequest,
    RetrieveResponse,
)
from .api.v11_api_server import (
    APP_TITLE,
    APP_VERSION,
    app,
    agent_analyze_export_endpoint,
    agent_analyze_endpoint,
    agent_answer_endpoint,
    agent_report_download_endpoint,
    agent_memory_reset_endpoint,
    get_agent,
    get_cfg,
    health,
    lifespan,
    openwebui_tool_spec,
    readiness,
    retrieve_context_endpoint,
    retrieve_endpoint,
)


__all__ = [
    "APP_TITLE",
    "APP_VERSION",
    "AgentAnalyzeRequest",
    "AgentAnalyzeResponse",
    "AgentAnalyzeExportRequest",
    "AgentAnswerRequest",
    "AgentAnswerResponse",
    "AgentMemoryResetRequest",
    "HealthResponse",
    "NeighborItem",
    "OpenWebUIToolSpecResponse",
    "RetrieveContextResponse",
    "RetrieveHit",
    "RetrieveRequest",
    "RetrieveResponse",
    "agent_analyze_export_endpoint",
    "agent_analyze_endpoint",
    "agent_answer_endpoint",
    "agent_report_download_endpoint",
    "agent_memory_reset_endpoint",
    "app",
    "get_agent",
    "get_cfg",
    "health",
    "lifespan",
    "openwebui_tool_spec",
    "readiness",
    "retrieve_context_endpoint",
    "retrieve_endpoint",
]


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("RAG_API_HOST", "0.0.0.0")
    port = int(os.getenv("RAG_API_PORT", "8000"))
    uvicorn.run("services.retrieval_service.v11_api_server:app", host=host, port=port, reload=False)
