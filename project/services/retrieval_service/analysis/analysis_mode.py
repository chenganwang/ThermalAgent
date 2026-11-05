from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class AnalysisModeResult:
    enabled: bool
    mode: str = "default_chat"
    reason: str = "ordinary_chat"
    requested_outputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ANALYSIS_TRIGGERS = (
    "生成分析报告",
    "分析报告",
    "项目分析报告",
    "分析文档",
    "Markdown 报告",
    "Markdown报告",
    "engineering report",
    "markdown report",
    "完整方案",
    "方案总结",
    "初步设计建议",
    "设计建议",
    "工程建议",
    "散热方案",
    "系统分析",
    "对比方案",
    "比较一下",
    "怎么选",
    "哪个更合适",
    "取舍",
    "风冷和液冷",
    "水和 EGW",
    "水和EGW",
    "W27 和 W32",
    "W27和W32",
    "5K 和 10K",
    "5K和10K",
    "输出报告",
    "仿真准备",
    "仿真前检查",
    "模型文件已上传",
    "边界条件",
    "simulation preparation",
    "cabinet model",
    "机柜模型分析",
    "散热路径图",
    "热阻网络图",
)

_MODEL_ANALYSIS_TERMS = (
    "分析",
    "仿真准备",
    "方案",
    "机柜",
    "散热",
    "报告",
)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _request_options(request_options: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(request_options or {})


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _requested_outputs(query: str, options: Mapping[str, Any]) -> list[str]:
    raw_outputs = options.get("requested_outputs") or []
    outputs = [str(item) for item in raw_outputs if str(item or "").strip()] if isinstance(raw_outputs, list) else []
    text = query or ""

    lowered = text.lower()

    if any(term in text for term in ("散热路径图", "热阻网络图", "图结构", "图示", "路径图", "画")):
        outputs.append("visualization")
    if any(term in text for term in ("生成分析报告", "分析报告", "项目分析报告", "输出报告", "报告", "分析文档", "形成文档", "Markdown 报告", "Markdown报告")) or any(
        term in lowered for term in ("engineering report", "markdown report", "summarize as")
    ):
        outputs.append("report")
    if any(term in text for term in ("完整方案", "方案总结", "初步方案", "方案", "初步设计建议", "设计建议", "工程建议", "散热方案", "系统分析")):
        outputs.append("solution_summary")
    if any(term in text for term in ("对比方案", "对比", "比较", "比较一下", "怎么选", "哪个更好", "哪个更合适", "取舍", "风冷和液冷", "水和 EGW", "水和EGW", "W27 和 W32", "W27和W32", "5K 和 10K", "5K和10K")):
        outputs.append("comparison")
    if (
        any(term in text for term in ("仿真准备", "机柜模型分析", "仿真", "模型文件", "边界条件", "仿真前检查", "STEP", "STP"))
        or any(term in lowered for term in ("simulation", "simulation preparation", "cabinet model"))
        or options.get("uploaded_model_file_id")
        or options.get("uploaded_model_filename")
        or options.get("uploaded_model_file_name")
    ):
        outputs.append("simulation")

    return _dedupe(outputs)


def detect_analysis_mode(
    query: str,
    request_options: Mapping[str, Any] | None = None,
    task_result: object | None = None,
) -> AnalysisModeResult:
    """Detect whether a request should enter optional analysis report mode.

    Ordinary chat remains the default. This function does not inspect files,
    run simulations, or alter task-understanding behavior.
    """

    options = _request_options(request_options)
    text = query or ""

    if _as_bool(options.get("analysis_report_mode")):
        return AnalysisModeResult(
            enabled=True,
            mode="analysis_report",
            reason="explicit_request_option",
            requested_outputs=_requested_outputs(text, options),
        )

    matched = [term for term in _ANALYSIS_TRIGGERS if term in text]
    if matched:
        return AnalysisModeResult(
            enabled=True,
            mode="analysis_report",
            reason=f"query_trigger:{matched[0]}",
            requested_outputs=_requested_outputs(text, options),
        )

    has_uploaded_model = bool(
        options.get("uploaded_model_file_id")
        or options.get("uploaded_model_filename")
        or options.get("uploaded_model_file_name")
    )
    if has_uploaded_model and any(term in text for term in _MODEL_ANALYSIS_TERMS):
        return AnalysisModeResult(
            enabled=True,
            mode="analysis_report",
            reason="uploaded_model_with_analysis_request",
            requested_outputs=_requested_outputs(text, options),
        )

    return AnalysisModeResult(enabled=False, requested_outputs=_requested_outputs(text, options))
