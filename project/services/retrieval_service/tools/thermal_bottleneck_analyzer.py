from __future__ import annotations

from copy import deepcopy
from typing import Any


def analyze_thermal_bottlenecks(
    elements: list[dict[str, Any]] | None,
    *,
    heat_load_w: float | None = None,
    topology: str = "series",
) -> dict[str, Any]:
    known = [
        deepcopy(row)
        for row in list(elements or [])
        if isinstance(row, dict) and row.get("resistance_k_per_w") is not None
    ]
    if not known:
        return {
            "generated": True,
            "status": "missing_params",
            "bottlenecks": [],
            "warnings": [],
            "missing_inputs": ["element_resistance_k_per_w"],
        }
    if any(float(row["resistance_k_per_w"]) <= 0 for row in known):
        return {
            "generated": True,
            "status": "missing_params",
            "bottlenecks": [],
            "warnings": ["thermal_resistance_must_be_positive"],
            "missing_inputs": ["positive_element_resistance_k_per_w"],
        }
    total = sum(float(row["resistance_k_per_w"]) for row in known)
    warnings: list[str] = []
    if heat_load_w is None:
        warnings.append("heat_load_missing")
    if str(topology).lower() == "parallel":
        warnings.append("parallel_bottleneck_interpretation_differs_from_series_temperature_rise_contribution")

    ranked = sorted(known, key=lambda row: float(row["resistance_k_per_w"]), reverse=True)
    bottlenecks: list[dict[str, Any]] = []
    for rank, row in enumerate(ranked, start=1):
        resistance = float(row["resistance_k_per_w"])
        bottlenecks.append(
            {
                "element_id": row.get("element_id"),
                "name": row.get("name"),
                "resistance_k_per_w": resistance,
                "delta_t_c": None if heat_load_w is None else float(heat_load_w) * resistance,
                "contribution_ratio": resistance / total,
                "rank": rank,
                "reason": "largest_temperature_rise_contribution" if heat_load_w is not None else "largest_resistance_ratio",
            }
        )
    return {
        "generated": True,
        "status": "success",
        "bottlenecks": bottlenecks,
        "warnings": warnings,
        "missing_inputs": [],
    }


__all__ = ["analyze_thermal_bottlenecks"]
