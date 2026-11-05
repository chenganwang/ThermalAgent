from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .comparison_engine import build_comparison
from .report_builder import build_analysis_report
from .solution_synthesizer import build_solution_summary
from ..simulation.heat_conduction_router import build_heat_conduction_1d_route, is_heat_conduction_1d_request
from ..simulation.model_file_registry import get_registered_model_file
from ..simulation.simulation_adapter import missing_model_file_payload, prepare_simulation_stub
from ..visualization.thermal_path_graph import build_graph, infer_graph_type
from ..visualization.request_graph import build_requested_visualization


@dataclass(frozen=True)
class AnalysisWorkflowResult:
    enabled: bool
    mode: str = "default_chat"
    requested_outputs: list[str] = field(default_factory=list)
    visualization: dict[str, Any] = field(default_factory=lambda: {"generated": False})
    simulation: dict[str, Any] = field(default_factory=lambda: {"enabled": False})
    solution: dict[str, Any] = field(default_factory=lambda: {"generated": False})
    comparison: dict[str, Any] = field(default_factory=lambda: {"generated": False})
    report: dict[str, Any] = field(default_factory=lambda: {"generated": False})
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_OUTPUT_ALIASES = {
    "visualization": "visualization",
    "graph": "visualization",
    "simulation": "simulation",
    "simulation_readiness": "simulation",
    "solution": "solution",
    "solution_summary": "solution",
    "comparison": "comparison",
    "decision": "comparison",
    "report": "report",
    "markdown_report": "report",
}

_OUTPUT_ORDER = ["visualization", "simulation", "solution", "comparison", "report"]

_GRAPH_TERMS = ("图", "路径", "热阻网络", "回路", "图结构", "散热路径")
_SIMULATION_TERMS = ("仿真", "模型", "机柜模型", "模型文件", "边界条件", "仿真前检查", "STEP", "STP", "simulation", "simulation preparation", "cabinet model")
_SOLUTION_TERMS = ("方案", "建议", "完整方案", "初步方案", "初步设计建议", "设计建议", "工程建议", "散热方案", "系统分析", "完整分析")
_COMPARISON_TERMS = ("对比", "比较", "比较一下", "哪个更好", "哪个更合适", "怎么选", "如何选择", "取舍")
_REPORT_TERMS = ("报告", "整理成报告", "Markdown", "markdown", "文档", "分析文档", "项目分析报告", "完整分析", "engineering report", "markdown report", "summarize as")
_COMPLETE_ANALYSIS_TERMS = ("完整分析报告", "完整分析", "分析报告")


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:400]


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    return {}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_requested_outputs(*collections: Any) -> list[str]:
    outputs: list[str] = []
    for collection in collections:
        if not isinstance(collection, (list, tuple, set)):
            continue
        for item in collection:
            normalized = _OUTPUT_ALIASES.get(str(item or "").strip().lower())
            if normalized:
                outputs.append(normalized)
    return [name for name in _OUTPUT_ORDER if name in set(outputs)]


def _contains_any(query: str, terms: tuple[str, ...]) -> bool:
    text = query or ""
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _has_uploaded_model(options: Mapping[str, Any]) -> bool:
    return bool(options.get("uploaded_model_file_id") or options.get("uploaded_model_filename") or options.get("uploaded_model_file_name"))


def _infer_outputs(query: str, options: Mapping[str, Any]) -> list[str]:
    outputs: list[str] = []
    complete_report = _contains_any(query, _COMPLETE_ANALYSIS_TERMS)

    if _contains_any(query, _GRAPH_TERMS) or complete_report:
        outputs.append("visualization")
    if _contains_any(query, _SIMULATION_TERMS) or (_has_uploaded_model(options) and complete_report):
        outputs.append("simulation")
    if _contains_any(query, _SOLUTION_TERMS) or complete_report:
        outputs.append("solution")
    if _contains_any(query, _COMPARISON_TERMS):
        outputs.append("comparison")
    if _contains_any(query, _REPORT_TERMS):
        outputs.append("report")

    return [name for name in _OUTPUT_ORDER if name in set(outputs)]


def _workflow_enabled(analysis_mode: Mapping[str, Any], explicit_outputs: list[str]) -> bool:
    return bool(analysis_mode.get("enabled")) or bool(explicit_outputs)


def _analysis_mode_for_output(analysis_mode: Mapping[str, Any], output: str) -> dict[str, Any]:
    mode = dict(analysis_mode)
    mode["enabled"] = True
    aliases = {
        "visualization": ["visualization"],
        "simulation": ["simulation"],
        "solution": ["solution", "solution_summary"],
        "comparison": ["comparison", "decision"],
        "report": ["report", "markdown_report"],
    }
    mode["requested_outputs"] = aliases.get(output, [output])
    return mode


def _build_visualization(query: str, calculation_metadata: dict | None = None) -> dict[str, Any]:
    return build_requested_visualization(query, calculation_metadata)


def _build_simulation(query: str, options: Mapping[str, Any]) -> dict[str, Any]:
    if is_heat_conduction_1d_request(query):
        return build_heat_conduction_1d_route(query)
    file_id = str(options.get("uploaded_model_file_id") or "").strip()
    filename = str(options.get("uploaded_model_filename") or options.get("uploaded_model_file_name") or "").strip()
    registered = get_registered_model_file(file_id, filename)
    if registered is None:
        return missing_model_file_payload()
    return prepare_simulation_stub(
        file_id=str(registered["file_id"]),
        filename=str(registered["filename"]),
        description=registered.get("description"),
        conditions=options.get("simulation_conditions") if isinstance(options.get("simulation_conditions"), dict) else None,
    )


def run_analysis_workflow(
    query: str,
    answer: str | None = None,
    task_result: object | dict | None = None,
    sources: list[dict] | None = None,
    calculation_metadata: dict | None = None,
    knowledge_metadata: dict | None = None,
    analysis_mode: dict | None = None,
    request_options: dict | None = None,
) -> dict[str, Any]:
    """Run optional analysis-report modules in a fixed, fault-tolerant order.

    The workflow is only an orchestrator: it does not call an LLM, access the
    database, run CFD, create images, or write report files.
    """

    mode = _as_mapping(analysis_mode)
    options = _as_mapping(request_options)
    explicit_outputs = _normalize_requested_outputs(mode.get("requested_outputs"), options.get("requested_outputs"))

    if not _workflow_enabled(mode, explicit_outputs):
        return AnalysisWorkflowResult(
            enabled=False,
            mode=str(mode.get("mode") or "default_chat"),
            requested_outputs=explicit_outputs,
        ).to_dict()

    inferred_outputs = _infer_outputs(query, options) if bool(mode.get("enabled")) else []
    requested_outputs = _dedupe(explicit_outputs + inferred_outputs)
    requested_outputs = [name for name in _OUTPUT_ORDER if name in set(requested_outputs)]

    visualization: dict[str, Any] = {"generated": False}
    simulation: dict[str, Any] = {"enabled": False}
    solution: dict[str, Any] = {"generated": False}
    comparison: dict[str, Any] = {"generated": False}
    report: dict[str, Any] = {"generated": False}
    warnings: list[str] = []
    errors: list[str] = []

    if "visualization" in requested_outputs:
        try:
            visualization = _build_visualization(query, calculation_metadata)
        except Exception as exc:
            error = _safe_error(exc)
            visualization = {"generated": False, "error": error}
            errors.append(f"visualization: {error}")

    if "simulation" in requested_outputs:
        try:
            simulation = _build_simulation(query, options)
        except Exception as exc:
            error = _safe_error(exc)
            simulation = {"enabled": False, "error": error}
            errors.append(f"simulation: {error}")

    if "solution" in requested_outputs:
        try:
            solution = build_solution_summary(
                query=query,
                task_result=task_result,
                sources=sources,
                calculation_metadata=calculation_metadata,
                knowledge_metadata=knowledge_metadata,
                visualization_metadata=visualization,
                simulation_metadata=simulation,
                analysis_mode=_analysis_mode_for_output(mode, "solution"),
            )
        except Exception as exc:
            error = _safe_error(exc)
            solution = {"generated": False, "error": error}
            errors.append(f"solution: {error}")

    if "comparison" in requested_outputs:
        try:
            comparison = build_comparison(
                query=query,
                task_result=task_result,
                sources=sources,
                calculation_metadata=calculation_metadata,
                solution_metadata=solution,
                visualization_metadata=visualization,
                simulation_metadata=simulation,
                analysis_mode=_analysis_mode_for_output(mode, "comparison"),
            )
        except Exception as exc:
            error = _safe_error(exc)
            comparison = {"generated": False, "error": error}
            errors.append(f"comparison: {error}")

    if "report" in requested_outputs:
        try:
            report = build_analysis_report(
                query=query,
                answer=answer,
                task_result=task_result,
                sources=sources,
                calculation_metadata=calculation_metadata,
                knowledge_metadata=knowledge_metadata,
                visualization_metadata=visualization,
                simulation_metadata=simulation,
                solution_metadata=solution,
                comparison_metadata=comparison,
                analysis_mode=_analysis_mode_for_output(mode, "report"),
            )
        except Exception as exc:
            error = _safe_error(exc)
            report = {"generated": False, "error": error}
            errors.append(f"report: {error}")

    if not requested_outputs:
        warnings.append("analysis_report_mode 已启用，但未识别到需要生成的分析输出。")

    return AnalysisWorkflowResult(
        enabled=True,
        mode=str(mode.get("mode") or "analysis_report"),
        requested_outputs=requested_outputs,
        visualization=visualization,
        simulation=simulation,
        solution=solution,
        comparison=comparison,
        report=report,
        warnings=warnings,
        errors=errors,
    ).to_dict()


__all__ = ["AnalysisWorkflowResult", "run_analysis_workflow"]
