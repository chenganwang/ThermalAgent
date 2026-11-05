from __future__ import annotations

from typing import Any, Callable

from ..analysis.analysis_mode import detect_analysis_mode
from ..analysis.workflow_orchestrator import run_analysis_workflow
from ..answering.knowledge_synthesizer import infer_knowledge_template, synthesize_knowledge_answer
from ..config import AppConfig
from ..conversation_memory import ConversationMemory
from ..critique.workflow import run_critique_workflow
from ..properties.formatter import format_property_lookup_result
from ..query_rewriter import QueryRewriteResult, rewrite_query
from ..rag_chain import generate_answer, hits_to_sources
from ..retriever import Hit
from ..task_understanding import TaskUnderstandingResult, understand_task
from ..tools.tool_registry import format_tool_answer
from .contracts import AgentRequest
from .metadata_builder import safe_error
from .stages.base import AgentStage
from .stages.calculation_stage import CalculationStage
from .stages.property_lookup_stage import PropertyLookupStage
from .state import AgentContext


RetrieverFunc = Callable[[AppConfig, str, int], tuple[list[Hit], int, Any]]


class AgentPipeline:
    """Minimal sequential pipeline runner for gradual stage migration."""

    def __init__(self, stages: list[AgentStage] | None = None, *, continue_on_error: bool = True) -> None:
        self.stages = list(stages or [])
        self.continue_on_error = bool(continue_on_error)

    def run(self, context: AgentContext) -> AgentContext:
        current = context
        for stage in self.stages:
            try:
                next_context = stage.run(current)
                if next_context is not None:
                    current = next_context
            except Exception as exc:
                stage_name = str(getattr(stage, "name", stage.__class__.__name__))
                current.errors.append(f"{stage_name}: {safe_error(exc)}")
                if not self.continue_on_error:
                    break
        return current


def resolve_conversation_context(memory: ConversationMemory, query: str, session_id: str) -> tuple[str, bool]:
    original = query or ""
    resolved = memory.resolve_references(session_id, original)
    used_memory = resolved != original
    if not used_memory:
        context = memory.get_context(session_id, max_turns=1)
        used_memory = bool(context.get("turns"))
    return resolved, used_memory


def run_task_understanding(query: str) -> TaskUnderstandingResult:
    return understand_task(query)


def run_query_rewriting(query: str, task: TaskUnderstandingResult) -> QueryRewriteResult:
    return rewrite_query(query, task)


def update_memory_state(
    memory: ConversationMemory,
    session_id: str,
    task: TaskUnderstandingResult,
    rewrite: QueryRewriteResult,
) -> None:
    memory.update_state(session_id, task, rewrite)


def build_retrieval_query(rewrite: QueryRewriteResult) -> str:
    parts = [rewrite.rewritten_query]
    for expanded in rewrite.expanded_queries[1:3]:
        if expanded and expanded not in parts:
            parts.append(expanded)
    return " ".join(parts).strip() or rewrite.original_query


def run_calculation(
    query: str,
    task: TaskUnderstandingResult | dict[str, Any] | None = None,
    *, observer=None,
) -> tuple[dict[str, Any] | None, str | None]:
    task_data = task.to_dict() if hasattr(task, "to_dict") else dict(task or {})
    context = AgentContext(
        request=AgentRequest(query=query),
        task=task_data,
        metadata={},
    )
    CalculationStage(observer=observer).run(context)
    return context.intermediate.get("calculation_result"), context.intermediate.get("calculation_error")


def run_property_lookup(query: str, task: TaskUnderstandingResult) -> tuple[dict[str, Any] | None, str | None]:
    context = AgentContext(
        request=AgentRequest(query=query),
        task=task.to_dict(),
        metadata={},
    )
    PropertyLookupStage().run(context)
    property_lookup = context.metadata.get("property_lookup") or {}
    if not property_lookup.get("used_property_lookup"):
        return None, None
    return context.intermediate.get("property_lookup_result"), context.intermediate.get("property_lookup_error")


def run_retrieval(
    *,
    cfg: AppConfig,
    retriever_func: RetrieverFunc,
    task: TaskUnderstandingResult,
    resolved_query: str,
    rewrite: QueryRewriteResult,
    top_k: int,
) -> tuple[list[Hit], int, str | None, dict[str, Any] | None]:
    hits: list[Hit] = []
    retrieval_latency_ms = 0
    retrieval_error: str | None = None
    retrieval_plan: dict[str, Any] | None = None

    if task.needs_retrieval and resolved_query.strip():
        try:
            hits, retrieval_latency_ms, plan = retriever_func(
                cfg,
                build_retrieval_query(rewrite),
                top_k,
            )
            if hasattr(plan, "to_dict"):
                retrieval_plan = plan.to_dict()
        except Exception as exc:
            retrieval_error = safe_error(exc)
            hits = []
    return hits, retrieval_latency_ms, retrieval_error, retrieval_plan


def build_sources(hits: list[Hit], cfg: AppConfig) -> list[dict[str, Any]]:
    return hits_to_sources(hits, cfg=cfg)


def run_answer_generation(
    *,
    resolved_query: str,
    task: TaskUnderstandingResult,
    hits: list[Hit],
    sources: list[dict[str, Any]],
    calculation_result: dict[str, Any] | None,
    property_lookup_result: dict[str, Any] | None = None,
) -> tuple[str, str]:
    knowledge_template = infer_knowledge_template(resolved_query, task.task_type)
    if calculation_result is not None:
        return format_tool_answer(calculation_result, sources=sources), knowledge_template
    if property_lookup_result is not None:
        return format_property_lookup_result(property_lookup_result), knowledge_template

    special_answer = None
    if knowledge_template in {"property_lookup", "irrelevant_or_analogy", "formula"}:
        special_answer = synthesize_knowledge_answer(
            resolved_query,
            task.task_type,
            sources,
            hits if knowledge_template not in {"formula"} else [],
        )
    answer_text = special_answer or generate_answer(
        resolved_query,
        task,
        hits,
        sources=sources,
    )
    return answer_text, knowledge_template


def add_memory_turn(
    *,
    memory: ConversationMemory,
    session_id: str,
    user_query: str,
    assistant_answer: str,
    resolved_query: str,
    task: TaskUnderstandingResult,
    hits_count: int,
    retrieval_error: str | None,
    calculation_result: dict[str, Any] | None,
) -> None:
    memory.add_turn(
        session_id,
        user_query=user_query,
        assistant_answer=assistant_answer,
        metadata={
            "resolved_query": resolved_query,
            "task_type": task.task_type,
            "entities": task.entities,
            "retrieval_count": hits_count,
            "retrieval_error": retrieval_error,
            "calculation_tool": calculation_result.get("tool_name") if calculation_result else None,
        },
    )


def run_analysis_mode_detection(
    query: str,
    request_options: dict[str, Any],
    task: TaskUnderstandingResult,
) -> Any:
    return detect_analysis_mode(query, request_options, task)


def run_analysis_workflow_stage(
    *,
    resolved_query: str,
    answer_text: str,
    task: TaskUnderstandingResult,
    sources: list[dict[str, Any]],
    calculation: dict[str, Any],
    knowledge: dict[str, Any],
    analysis_mode_meta: dict[str, Any],
    request_options: dict[str, Any],
) -> dict[str, Any]:
    return run_analysis_workflow(
        query=resolved_query,
        answer=answer_text,
        task_result=task,
        sources=sources,
        calculation_metadata=calculation,
        knowledge_metadata=knowledge,
        analysis_mode=analysis_mode_meta,
        request_options=request_options,
    )


def run_self_critique_stage(
    *,
    resolved_query: str,
    answer_text: str,
    sources: list[dict[str, Any]],
    metadata: dict[str, Any],
    task: TaskUnderstandingResult,
    rewrite: QueryRewriteResult,
) -> str:
    try:
        metadata["self_critique"] = run_critique_workflow(
            query=resolved_query,
            answer=answer_text,
            sources=sources,
            metadata=metadata,
            task=task.to_dict(),
            rewrite=rewrite.to_dict(),
            enable_repair=True,
            max_repair_attempts=1,
        )
        if metadata["self_critique"].get("repaired") and metadata["self_critique"].get("final_answer"):
            return str(metadata["self_critique"]["final_answer"])
        return answer_text
    except Exception as exc:
        metadata["self_critique"] = {
            "enabled": False,
            "passed": False,
            "severity": "error",
            "issues": [],
            "repair_action": "none",
            "route": "finalize_with_warning",
            "requires_human_review": False,
            "workflow": {
                "enabled": False,
                "version": "critic_workflow_v1",
            },
            "trace": [],
            "repair_attempts": 0,
            "repaired": False,
            "original_answer": answer_text,
            "final_answer": answer_text,
            "original_route": "finalize_with_warning",
            "final_route": "finalize_with_warning",
            "error": safe_error(exc),
        }
        return answer_text


__all__ = [
    "AgentPipeline",
    "RetrieverFunc",
    "add_memory_turn",
    "build_retrieval_query",
    "build_sources",
    "resolve_conversation_context",
    "run_analysis_mode_detection",
    "run_analysis_workflow_stage",
    "run_answer_generation",
    "run_calculation",
    "run_property_lookup",
    "run_query_rewriting",
    "run_retrieval",
    "run_self_critique_stage",
    "run_task_understanding",
    "update_memory_state",
]
