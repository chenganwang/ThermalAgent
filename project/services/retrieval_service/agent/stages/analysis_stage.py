from __future__ import annotations

from typing import Any, Callable

from ...analysis.analysis_mode import detect_analysis_mode
from ...analysis.report_template_registry import select_template
from ...analysis.report_templates import apply_report_template
from ...analysis.workflow_orchestrator import run_analysis_workflow
from ...simulation.simulation_task_builder import build_simulation_task_builder
from ..metadata_builder import ensure_metadata_contract, package_analysis_metadata, safe_error
from ..retrieval_observability import build_retrieval_observability
from ..state import AgentContext
from .base import BaseAgentStage


class AnalysisStage(BaseAgentStage):
    """Wrap existing analysis packaging without changing its business logic."""

    name = "analysis"

    def __init__(
        self,
        *,
        mode_detector: Callable[..., Any] = detect_analysis_mode,
        workflow_runner: Callable[..., dict[str, Any]] = run_analysis_workflow,
    ) -> None:
        self.mode_detector = mode_detector
        self.workflow_runner = workflow_runner

    def run(self, context: AgentContext) -> AgentContext:
        context.metadata = ensure_metadata_contract(context.metadata)
        protected_report_content = (context.metadata.get("report") or {}).get("content")
        protected_visualization_graph = (context.metadata.get("visualization") or {}).get("graph")
        protected_simulation_task_builder = (context.metadata.get("simulation") or {}).get("task_builder")
        options = self._request_options(context)
        mode_data = dict(context.metadata.get("analysis_mode") or {})
        workflow: dict[str, Any] = {
            "enabled": False,
            "mode": "default_chat",
            "requested_outputs": [],
            "warnings": [],
            "errors": [],
        }

        try:
            detected = self.mode_detector(context.request.query, options, context.task)
            mode_data = self._as_dict(detected)
            workflow = dict(
                self.workflow_runner(
                    query=context.request.query,
                    answer=context.answer,
                    task_result=context.task,
                    sources=context.sources,
                    calculation_metadata=context.metadata.get("calculation") or {},
                    knowledge_metadata=context.metadata.get("knowledge") or {},
                    analysis_mode=mode_data,
                    request_options=options,
                )
                or {}
            )
        except Exception as exc:
            error = safe_error(exc)
            context.errors.append(f"{self.name}: {error}")
            workflow["errors"] = [error]

        context.metadata = package_analysis_metadata(context.metadata, mode_data, workflow)
        if protected_report_content is not None:
            context.metadata["report"]["content"] = protected_report_content
        if protected_visualization_graph is not None:
            context.metadata["visualization"]["graph"] = protected_visualization_graph
        if protected_simulation_task_builder is not None:
            context.metadata["simulation"]["task_builder"] = protected_simulation_task_builder
        context.intermediate["analysis_result"] = workflow
        context.intermediate["report_result"] = context.metadata["report"]
        context.intermediate["visualization_result"] = context.metadata["visualization"]
        context.intermediate["simulation_result"] = context.metadata["simulation"]
        self._package_report_template_and_simulation_task(context, options)
        self._package_retrieval_observability(context)
        return context

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            converted = value.to_dict()
            return dict(converted) if isinstance(converted, dict) else {}
        return {}

    @staticmethod
    def _request_options(context: AgentContext) -> dict[str, Any]:
        options = dict(context.request.options or {})
        requested = list(options.get("requested_outputs") or context.request.requested_outputs or [])
        task = dict(context.task or {})
        flag_outputs = (
            ("requires_report", "report"),
            ("needs_report", "report"),
            ("requires_comparison", "comparison"),
            ("needs_comparison", "comparison"),
            ("requires_visualization", "visualization"),
            ("needs_visualization", "visualization"),
            ("requires_simulation_readiness", "simulation"),
            ("needs_simulation", "simulation"),
        )
        for flag, output in flag_outputs:
            if bool(task.get(flag)) and output not in requested:
                requested.append(output)
        task_output = {
            "report": "report",
            "comparison": "comparison",
            "visualization": "visualization",
            "simulation_readiness": "simulation",
        }.get(str(task.get("task_type") or ""))
        if task_output and task_output not in requested:
            requested.append(task_output)
        options["requested_outputs"] = requested
        if context.request.analysis_report_mode or task.get("analysis_report_mode") or requested:
            options["analysis_report_mode"] = True
        if context.request.uploaded_model_file_id and not options.get("uploaded_model_file_id"):
            options["uploaded_model_file_id"] = context.request.uploaded_model_file_id
        if context.request.uploaded_model_filename and not options.get("uploaded_model_filename"):
            options["uploaded_model_filename"] = context.request.uploaded_model_filename
        return options

    @staticmethod
    def _package_retrieval_observability(context: AgentContext) -> None:
        retrieval_result = context.intermediate.get("retrieval_result")
        retrieval_data = retrieval_result if isinstance(retrieval_result, dict) else {}
        observability = build_retrieval_observability(
            query=context.request.query,
            retrieval_query=retrieval_data.get("query"),
            sources=context.sources,
            hits=context.intermediate.get("retrieval_hits") if isinstance(context.intermediate.get("retrieval_hits"), list) else None,
        )
        context.intermediate["retrieval_observability"] = observability
        context.metadata["retrieval"] = observability

    @staticmethod
    def _package_report_template_and_simulation_task(context: AgentContext, options: dict[str, Any]) -> None:
        report = context.metadata.get("report") if isinstance(context.metadata.get("report"), dict) else {"generated": False}
        comparison = context.metadata.get("comparison") if isinstance(context.metadata.get("comparison"), dict) else {"generated": False}
        simulation = context.metadata.get("simulation") if isinstance(context.metadata.get("simulation"), dict) else {"enabled": False}
        triggered = bool(report.get("generated") or comparison.get("generated") or simulation.get("enabled"))
        if not triggered:
            return

        template = select_template(context.task, options, context.metadata)
        context.intermediate["report_template"] = template.to_dict()
        if report.get("generated"):
            context.metadata["report"] = apply_report_template(report, template)
            if bool((context.metadata.get("thermal_network") or {}).get("generated")):
                context.metadata["report"].setdefault("render_hints", {})["thermal_network_cards"] = True
            context.intermediate["report_result"] = context.metadata["report"]
        elif comparison.get("generated"):
            comparison["report_template_id"] = template.template_id
            comparison["report_render_hints"] = dict(template.render_hints)
            context.metadata["comparison"] = comparison
        if simulation.get("enabled"):
            simulation["report_template_id"] = template.template_id
            simulation["report_render_hints"] = dict(template.render_hints)
            model_file = simulation.get("model_file") if isinstance(simulation.get("model_file"), dict) else None
            builder_result = build_simulation_task_builder(
                query=context.request.query,
                model_file=model_file,
                conditions=options.get("simulation_conditions") if isinstance(options.get("simulation_conditions"), dict) else None,
                task=context.task,
                metadata=context.metadata,
                sources=context.sources,
            )
            simulation["task_builder"] = builder_result.to_dict()
            context.intermediate["simulation_task_builder_result"] = builder_result.to_dict()
            context.metadata["simulation"] = simulation
            context.intermediate["simulation_result"] = simulation


__all__ = ["AnalysisStage"]
