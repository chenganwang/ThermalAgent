from __future__ import annotations

from typing import Any

from .normalizer import has_any, normalize_query


_VISUALIZATION_TERMS = (
    "画图",
    "画一个",
    "图结构",
    "散热路径图",
    "热阻网络",
    "液冷回路",
    "示意图",
    "流程图",
    "曲线",
    "趋势图",
    "异常链",
    "故障链",
    "拓扑",
    "节点",
    "graph",
    "visualization",
    "diagram",
)

_PATH_TERMS = (
    "芯片-tim-冷板",
    "芯片到 tim",
    "芯片到tim",
    "芯片—tim—冷板",
    "芯片-tim-冷板-冷却液-cdu",
    "芯片—tim—冷板—冷却液—cdu",
)


def detect_visualization_intent(query: str) -> dict[str, Any]:
    """Detect graph/diagram request intent without generating graphics."""

    normalized = normalize_query(query)
    lowered = normalized.lower()
    signals: list[str] = []
    if has_any(normalized, _VISUALIZATION_TERMS):
        signals.append("visualization_keyword")
    if any(term in lowered for term in _PATH_TERMS):
        signals.append("thermal_path_sequence")
    if "冷板" in normalized and "cdu" in lowered and ("路径" in normalized or "回路" in normalized):
        signals.append("thermal_loop_entities")

    return {
        "needs_visualization": bool(signals),
        "signals": signals,
    }
