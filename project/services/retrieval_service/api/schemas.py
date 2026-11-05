from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from services.simulation_service.reference import LayeredWallRequest


class RetrieveRequest(BaseModel):
    query: str = Field(..., description="Natural-language retrieval query")
    top_k: int = Field(default=5, ge=1, le=20)
    neighbor_window: int = Field(default=1, ge=0, le=5)
    include_neighbors: bool = Field(default=True)
    include_context: bool = Field(default=True)
    include_query_plan: bool = Field(default=False)


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


class NeighborItem(BaseModel):
    chunk_id: int
    doc_id: int
    chunk_index: int
    page_start: int
    page_end: int
    chunk_type: str
    section_path: str | None = None
    token_len: int | None = None
    text: str


class RetrieveHit(BaseModel):
    rank: int
    score: float
    vector_score: float
    bm25_score: float
    lexical_score: float
    doc_id: int
    chunk_index: int
    page_start: int
    page_end: int
    chunk_id: int
    chunk_type: str = "text"
    text: str = ""
    expanded_text: str = ""
    neighbors: list[NeighborItem] = Field(default_factory=list)
    section_path: str | None = None
    token_len: int | None = None
    vector_pos: int | None = None
    retrieval_routes: list[str] = Field(default_factory=list)
    exact_reference_matches: list[str] = Field(default_factory=list)


class RetrieveResponse(BaseModel):
    query: str
    top_k: int
    neighbor_window: int
    latency_ms: int
    hits: list[RetrieveHit]
    context: str | None = None
    query_plan: dict[str, Any] | None = None


class RetrieveContextResponse(BaseModel):
    query: str
    top_k: int
    neighbor_window: int
    latency_ms: int
    context: str
    hit_count: int
    query_plan: dict[str, Any] | None = None


class OpenWebUIToolSpecResponse(BaseModel):
    name: str
    description: str
    http_endpoint: str
    auth: str


class AgentAnswerRequest(BaseModel):
    engineering_project_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,96}$")
    reference_solver: LayeredWallRequest | None = None
    design_criteria: dict[str, Any] | None = None

    @field_validator("design_criteria", mode="before")
    @classmethod
    def validate_design_criteria(cls, value):
        if value is None:
            return None
        from services.engineering_service.design_contracts import DesignCriteria
        return DesignCriteria.model_validate(value).model_dump(mode="json", exclude_none=True)
    query: str = Field(..., description="User question for the thermal agent")
    session_id: str = Field(default="default")
    top_k: int = Field(default=5, ge=1, le=20)
    analysis_report_mode: bool = Field(default=False)
    requested_outputs: list[str] = Field(default_factory=list)
    uploaded_model_file_id: str | None = None
    uploaded_model_filename: str | None = None
    simulation_mode: bool = Field(default=False)
    simulation_action: Literal["plan", "confirm", "cancel", "revise", "status"] | None = None
    simulation_plan_id: str | None = None


class AgentAnalyzeRequest(BaseModel):
    query: str = Field(..., description="User question to analyze without retrieval")
    session_id: str = Field(default="default")


class AgentAnalyzeExportRequest(BaseModel):
    engineering_project_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,96}$")
    reference_solver: LayeredWallRequest | None = None
    design_criteria: dict[str, Any] | None = None

    @field_validator("design_criteria", mode="before")
    @classmethod
    def validate_design_criteria(cls, value):
        if value is None:
            return None
        from services.engineering_service.design_contracts import DesignCriteria
        return DesignCriteria.model_validate(value).model_dump(mode="json", exclude_none=True)
    query: str = Field(..., description="User question for analysis report export")
    session_id: str = Field(default="default")
    top_k: int = Field(default=5, ge=1, le=20)
    export_report: bool = Field(default=True)
    export_formats: list[str] = Field(default_factory=list)
    export_format: str | None = None
    requested_outputs: list[str] = Field(default_factory=list)
    uploaded_model_file_id: str | None = None
    uploaded_model_filename: str | None = None
    title: str | None = None


class AgentMemoryResetRequest(BaseModel):
    session_id: str = Field(default="default")


class AgentAnswerResponse(BaseModel):
    answer: str
    query: str | None = None
    task_type: str | None = None
    retrieval_count: int = 0
    task: dict[str, Any]
    rewrite: dict[str, Any]
    sources: list[dict[str, Any]]
    session_id: str
    metadata: dict[str, Any]


class AgentAnalyzeResponse(BaseModel):
    resolved_query: str
    task: dict[str, Any]
    rewrite: dict[str, Any]


__all__ = [
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
]
