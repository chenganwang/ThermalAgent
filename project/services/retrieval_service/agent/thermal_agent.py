from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Callable

from ..config import AppConfig, load_config
from ..conversation_memory import ConversationMemory
from ..query_rewriter import QueryRewriteResult
from ..retrieval.retrieval_adapter import retrieve_for_agent
from ..retriever import Hit
from ..task.model_assist import classify_task_with_model
from ..task.shadow_mode import build_task_model_assist_metadata
from ..task_understanding import TaskUnderstandingResult
from .contracts import AgentRequest
from .metadata_builder import (
    build_agent_metadata,
    build_default_metadata,
    build_knowledge_metadata,
    calculation_metadata as _calculation_metadata,
    property_lookup_metadata as _property_lookup_metadata,
    safe_error as _safe_error,
    merge_metadata,
)
from .multi_agent.metadata import attach_multi_agent_metadata
from .engineering_run import finish_engineering_run
from services.engineering_service.execution import RunRecorder, execute_reference, local_report_content, reference_plan
from services.engineering_service.result_identity import ResultIdentityError, assert_agent_result
from .pipeline import (
    add_memory_turn,
    build_retrieval_query,
    resolve_conversation_context,
    run_answer_generation,
    run_calculation,
    run_property_lookup,
    update_memory_state,
)
from .response_builder import build_agent_response
from .stages.answer_stage import AnswerStage
from .stages.analysis_stage import AnalysisStage
from .stages.critique_stage import CritiqueStage
from .stages.retrieval_stage import RetrievalStage
from .stages.rewrite_stage import RewriteStage
from .stages.task_stage import TaskStage
from .state import AgentContext
from ..simulation.simulation_orchestrator import SimulationModeOrchestrator


RetrieverFunc = Callable[[AppConfig, str, int], tuple[list[Hit], int, Any]]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _default_retriever(cfg: AppConfig, query: str, top_k: int) -> tuple[list[Hit], int, Any]:
    return retrieve_for_agent(cfg, query, top_k)


def _option_bool(options: dict[str, Any], key: str, default: bool = False) -> bool:
    if key not in options:
        return default
    value = options.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _task_model_assist_shadow_enabled(options: dict[str, Any]) -> bool:
    return _option_bool(
        options,
        "task_model_assist_shadow",
        _env_bool("TASK_MODEL_ASSIST_SHADOW_ENABLED", False),
    )


def _task_model_assist_model_enabled() -> bool:
    return _env_bool("TASK_MODEL_ASSIST_ENABLED", False)


def _task_model_assist_error_metadata(
    *,
    task: TaskUnderstandingResult,
    model_enabled_by_config: bool,
    error: str,
) -> dict[str, Any]:
    return build_task_model_assist_metadata(
        query=task.original_query,
        rule_result=task.to_dict(),
        model_result={
            "enabled": True,
            "model_available": False,
            "used_for_routing": False,
            "task_type": None,
            "confidence": None,
            "candidate_tools": [],
            "flags": {},
            "warnings": ["task_model_assist_shadow_error"],
            "error": error,
        },
        model_enabled_by_config=model_enabled_by_config,
        shadow_enabled=True,
    )


def _build_task_model_assist_metadata(
    *,
    query: str,
    task: TaskUnderstandingResult,
    options: dict[str, Any],
) -> dict[str, Any] | None:
    if not _task_model_assist_shadow_enabled(options):
        return None

    model_enabled_by_config = _task_model_assist_model_enabled()
    try:
        model_result = classify_task_with_model(
            query=query,
            context={"rule_result": task.to_dict()},
            enable_model=model_enabled_by_config,
        )
        return build_task_model_assist_metadata(
            query=query,
            rule_result=task.to_dict(),
            model_result=model_result,
            model_enabled_by_config=model_enabled_by_config,
            shadow_enabled=True,
        )
    except Exception as exc:
        return _task_model_assist_error_metadata(
            task=task,
            model_enabled_by_config=model_enabled_by_config,
            error=_safe_error(exc),
        )


@dataclass(frozen=True)
class AgentAnalysis:
    resolved_query: str
    task: TaskUnderstandingResult
    rewrite: QueryRewriteResult
    used_memory: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolved_query": self.resolved_query,
            "task": self.task.to_dict(),
            "rewrite": self.rewrite.to_dict(),
            "used_memory": self.used_memory,
        }


class ThermalAgent:
    """Basic thermal-management knowledge agent.

    The orchestrator is intentionally conservative: it performs task
    understanding, query rewriting, retrieval, source tracking, optional local
    deterministic engineering estimates, answer generation, and short-term
    memory. It does not depend on external commercial LLM APIs.
    """

    def __init__(
        self,
        cfg: AppConfig | None = None,
        memory: ConversationMemory | None = None,
        retriever_func: RetrieverFunc | None = None,
        enable_llm: bool | None = None,
        simulation_orchestrator: SimulationModeOrchestrator | None = None,
        engineering_store=None,
    ) -> None:
        self.cfg = cfg or load_config()
        self.memory = memory or ConversationMemory()
        self.retriever_func = retriever_func or _default_retriever
        self.enable_llm = _env_bool("AGENT_ENABLE_LLM", False) if enable_llm is None else bool(enable_llm)
        self.simulation_orchestrator = simulation_orchestrator or SimulationModeOrchestrator()
        self.engineering_store = engineering_store

    def analyze(self, query: str, session_id: str = "default") -> AgentAnalysis:
        resolved, used_memory = resolve_conversation_context(self.memory, query, session_id)
        task_context = AgentContext(
            request=AgentRequest(query=resolved, session_id=session_id),
        )
        TaskStage().run(task_context)
        task_result = task_context.intermediate.get("task_result")
        if isinstance(task_result, TaskUnderstandingResult):
            task = task_result
        else:
            task = TaskUnderstandingResult(
                task_type="unknown",
                needs_retrieval=False,
                original_query=resolved,
                normalized_query=resolved,
                warnings=list(task_context.warnings),
            )
        RewriteStage().run(task_context)
        rewrite_result = task_context.intermediate.get("rewrite_result")
        if isinstance(rewrite_result, QueryRewriteResult):
            rewrite = rewrite_result
        else:
            rewrite = QueryRewriteResult(
                original_query=resolved,
                rewritten_query=resolved,
                expanded_queries=[resolved] if resolved else [],
            )
        update_memory_state(self.memory, session_id, task, rewrite)
        return AgentAnalysis(resolved_query=resolved, task=task, rewrite=rewrite, used_memory=used_memory)

    def _retrieval_query(self, rewrite: QueryRewriteResult) -> str:
        return build_retrieval_query(rewrite)

    def answer(
        self,
        query: str,
        session_id: str = "default",
        top_k: int | None = None,
        request_options: dict[str, Any] | None = None,
        *, stage_observer=None, calculation_observer=None,
    ) -> dict[str, Any]:
        options = dict(request_options or {})
        # Normalize the new user input before conversation rewriting or scalar
        # tool selection. A multilayer request must never fall through to the
        # legacy first-layer-only wall parser, including direct API clients.
        if not (options.get("simulation_mode") or options.get("simulation_action") or options.get("simulation_plan_id")
                or re.search(r"MATLAB|Simulink", query, re.I)):
            from services.engineering_service.task_input_parser import explicit_wall_inputs
            from services.engineering_service.task_contracts import DesignCriteria
            try:
                normalized = explicit_wall_inputs({**options, "query": query})
                if normalized.get("reference_solver") is not None:
                    options["reference_solver"] = normalized["reference_solver"]
                    if normalized.get("design_criteria") is not None:
                        options["design_criteria"] = DesignCriteria.model_validate(normalized["design_criteria"]).model_dump(mode="json", exclude_none=True)
                elif options.get("design_criteria") is not None:
                    raise ValueError("同步设计指标检查需要明确的多层导热参考模型；液冷设计指标请使用工程任务入口。")
            except ValueError as error:
                message = "多层导热输入需要确认：" + str(error).splitlines()[0][:240]
                return build_agent_response(answer_text=message, query=query, session_id=session_id,
                    task_type="clarification", task={"task_type": "clarification", "needs_calculation": False, "needs_retrieval": False},
                    rewrite={"original_query": query}, sources=[],
                    metadata={"engineering_input_error": {"code": "MULTILAYER_INPUT_INVALID", "message": message}, "used_calculation": False})
        recorder = RunRecorder(self.engineering_store, {"query": query, "session_id": session_id},
                               options.get("engineering_project_id") or "local")
        try:
            return self._answer_with_recorder(query, session_id, top_k, options, recorder, stage_observer, calculation_observer)
        except ResultIdentityError:
            message = "结果与本次输入、会话或设计指标不一致，已拒绝返回该结果。请重新确认输入后执行。"
            return build_agent_response(answer_text=message, query=query, session_id=session_id,
                task_type="error", task={"task_type": "error", "needs_calculation": False, "needs_retrieval": False},
                rewrite={"original_query": query}, sources=[],
                metadata={"engineering_result_error": {"code": "RESULT_IDENTITY_MISMATCH", "message": message}, "used_calculation": False})
        finally:
            recorder.close()

    def _answer_with_recorder(
        self,
        query: str,
        session_id: str = "default",
        top_k: int | None = None,
        request_options: dict[str, Any] | None = None,
        recorder=None,
        stage_observer=None,
        calculation_observer=None,
    ) -> dict[str, Any]:
        def event(step_id, status, detail, **data):
            if stage_observer is not None:
                stage_observer(step_id, status, detail, **data)

        def observe_run(run, result=None, report=None):
            run["session_id"] = session_id
            identity = (request_options or {}).get("_engineering_task_identity") or {}
            for key in ("task_id", "request_fingerprint"):
                if identity.get(key):
                    run[key] = identity[key]
            recorder(run, result, report)
            if calculation_observer is not None:
                calculation_observer(run, result, report)

        top_k = int(top_k or os.getenv("AGENT_TOP_K", "5"))
        event("structure_inputs", "running", "正在理解问题和整理检索计划。")
        analysis = self.analyze(query, session_id=session_id)
        event("structure_inputs", "completed", "问题结构与检索改写已生成。", outputs={"task_type": analysis.task.task_type})
        options = dict(request_options or {})
        recorder.request["resolved_query"] = analysis.resolved_query
        event("calculation", "running", "检查和执行本问题所需的白名单计算工具。")
        if options.get("reference_solver") is not None:
            calculation_result = execute_reference(reference_plan(options["reference_solver"], options.get("design_criteria")), observe_run)
            calculation_error = calculation_result.get("error")
        elif self.engineering_store is not None or calculation_observer is not None:
            calculation_result, calculation_error = run_calculation(analysis.resolved_query, analysis.task, observer=observe_run)
        else:
            calculation_result, calculation_error = run_calculation(analysis.resolved_query, analysis.task)
        if calculation_result is None:
            event("calculation", "skipped", "该问题不需要确定性数值计算。")
            event("validation", "skipped", "没有数值输出需要验证。")
        elif not calculation_result.get("engineering_run"):
            event("calculation", "completed" if calculation_result.get("status") == "ok" else "failed", "既有工具调用已返回。", outputs=calculation_result.get("result") or {})
            event("validation", "incomplete", "该既有工具未提供共享数值校验证据。")
        engineering_run = calculation_result.pop("engineering_run", None) if calculation_result else None
        design_review = None
        if options.get("reference_solver") is not None and options.get("design_criteria"):
            from services.engineering_service.design_review import evaluate_design
            design_review = evaluate_design(options["design_criteria"], (calculation_result or {}).get("result") or {})
            if engineering_run is not None:
                engineering_run["design_review"] = design_review
        event("properties", "running", "检查是否需要物性查询。")
        property_lookup_result, property_lookup_error = run_property_lookup(analysis.resolved_query, analysis.task)
        event("properties", "failed" if property_lookup_error else "completed" if property_lookup_result else "skipped", "物性查询已返回。" if property_lookup_result else "本问题没有物性查询结果。")
        event("retrieval", "running", "执行知识检索与来源整理。")
        retrieval_context = AgentContext(
            request=AgentRequest(
                query=analysis.resolved_query,
                session_id=session_id,
                top_k=top_k,
            ),
            task=analysis.task.to_dict(),
            rewrite=analysis.rewrite.to_dict(),
            intermediate={"rewrite_result": analysis.rewrite},
        )
        RetrievalStage(cfg=self.cfg, retriever_func=self.retriever_func).run(retrieval_context)
        retrieval_result = dict(retrieval_context.intermediate.get("retrieval_result") or {})
        hits = list(retrieval_context.intermediate.get("retrieval_hits") or [])
        sources = list(retrieval_context.sources)
        source_count = len(sources)
        retrieval_latency_ms = int(retrieval_result.get("latency_ms") or 0)
        retrieval_error = retrieval_result.get("error")
        retrieval_plan = retrieval_result.get("plan")
        event("retrieval", "failed" if retrieval_error else "completed" if sources else "incomplete", f"实际返回 {source_count} 条来源。", outputs={"retrieval_count": source_count})
        answer_text, knowledge_template = run_answer_generation(
            resolved_query=analysis.resolved_query,
            task=analysis.task,
            hits=hits,
            sources=sources,
            calculation_result=calculation_result,
            property_lookup_result=property_lookup_result,
        )
        calculation = _calculation_metadata(calculation_result)
        property_lookup = _property_lookup_metadata(property_lookup_result)
        if property_lookup_error and not property_lookup.get("error"):
            property_lookup["error"] = property_lookup_error
        knowledge = build_knowledge_metadata(
            calculation_result=calculation_result,
            sources=sources,
            knowledge_template=knowledge_template,
        )
        metadata_defaults = build_default_metadata()
        metadata = build_agent_metadata(
            hits_count=source_count,
            retrieval_latency_ms=retrieval_latency_ms,
            retrieval_error=retrieval_error,
            retrieval_plan=retrieval_plan,
            used_memory=analysis.used_memory,
            calculation=calculation,
            calculation_result=calculation_result,
            calculation_error=calculation_error,
            knowledge=knowledge,
            analysis_mode_meta=metadata_defaults["analysis_mode"],
            analysis_workflow=metadata_defaults["analysis_workflow"],
            llm_enabled=self.enable_llm,
            property_lookup=property_lookup,
        )
        simulation_response = self.simulation_orchestrator.handle(query, session_id, options)
        if simulation_response.metadata:
            metadata = merge_metadata(metadata, simulation_response.metadata)
        if simulation_response.handled:
            answer_text = simulation_response.answer
        add_memory_turn(
            memory=self.memory,
            session_id=session_id,
            user_query=query,
            assistant_answer=answer_text,
            resolved_query=analysis.resolved_query,
            task=analysis.task,
            hits_count=source_count,
            retrieval_error=retrieval_error,
            calculation_result=calculation_result,
        )
        analysis_context = AgentContext(
            request=AgentRequest(
                query=analysis.resolved_query,
                session_id=session_id,
                top_k=top_k,
                analysis_report_mode=bool(options.get("analysis_report_mode", False)),
                requested_outputs=list(options.get("requested_outputs") or []),
                uploaded_model_file_id=options.get("uploaded_model_file_id"),
                uploaded_model_filename=options.get("uploaded_model_filename"),
                options=options,
            ),
            task=analysis.task.to_dict(),
            rewrite=analysis.rewrite.to_dict(),
            sources=sources,
            answer=answer_text,
            metadata=metadata,
            intermediate={
                "calculation_result": calculation_result,
                "property_lookup_result": property_lookup_result,
                "retrieval_hits": hits,
                "retrieval_result": retrieval_result,
            },
        )
        event("report", "running", "执行原工程分析与报告生成流程。")
        AnalysisStage().run(analysis_context)
        if options.get("reference_solver") is not None and engineering_run is not None:
            from services.engineering_service.design_review import design_review_markdown
            reference_content = local_report_content(engineering_run) + design_review_markdown(design_review)
            analysis_context.answer = reference_content
            if options.get("analysis_report_mode") or "report" in (options.get("requested_outputs") or []):
                analysis_context.metadata["report"] = {"generated": True, "title": "一维多层壁参考计算报告", "content": reference_content}
        CritiqueStage().run(analysis_context)
        metadata = analysis_context.metadata
        if design_review is not None:
            metadata["design_review"] = design_review
        if engineering_run is not None:
            if design_review is not None and not design_review["passed"] and engineering_run["status"] == "completed":
                engineering_run["status"] = "incomplete"
            metadata["engineering_run"] = finish_engineering_run(engineering_run, metadata, sources)
            recorder(metadata["engineering_run"], calculation_result,
                     (metadata.get("report") or {}).get("content") if (metadata.get("report") or {}).get("generated") else None)
            metadata["engineering_run"]["persistence"] = dict(recorder.state)
            if calculation_result and calculation_result.get("reference_solver"):
                metadata["reference_solver"] = calculation_result["reference_solver"]
        report = metadata.get("report") or {}
        event("report", "failed" if report.get("error") else "completed" if report.get("generated") else "skipped",
              "报告已生成。" if report.get("generated") else "本次未生成报告。",
              outputs={"generated": bool(report.get("generated"))})
        recorder.close()
        answer_text = analysis_context.answer
        task_model_assist = _build_task_model_assist_metadata(
            query=analysis.resolved_query,
            task=analysis.task,
            options=options,
        )
        if task_model_assist is not None:
            metadata["task_model_assist"] = task_model_assist

        final_context = AgentContext(
            request=AgentRequest(
                query=query,
                session_id=session_id,
                top_k=top_k,
                analysis_report_mode=bool(options.get("analysis_report_mode", False)),
                requested_outputs=list(options.get("requested_outputs") or []),
                uploaded_model_file_id=options.get("uploaded_model_file_id"),
                uploaded_model_filename=options.get("uploaded_model_filename"),
                options=options,
            ),
            task=analysis.task.to_dict(),
            rewrite=analysis.rewrite.to_dict(),
            sources=sources,
            answer=answer_text,
            metadata=metadata,
        )
        event("answer", "running", "整理最终回答及来源合同。")
        AnswerStage().run(final_context)
        attach_multi_agent_metadata(final_context)
        result = build_agent_response(final_context)
        assert_agent_result(result)
        event("answer", "completed", "最终回答已生成。")
        return result

    def reset_memory(self, session_id: str = "default") -> None:
        self.memory.reset(session_id)
        self.simulation_orchestrator.reset(session_id)


__all__ = [
    "AgentAnalysis",
    "RetrieverFunc",
    "ThermalAgent",
    "_calculation_metadata",
    "_default_retriever",
    "_env_bool",
    "_safe_error",
]
