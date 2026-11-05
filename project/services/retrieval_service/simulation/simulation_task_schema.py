from __future__ import annotations

from typing import Any, Mapping

from .simulation_readiness_checker import check_simulation_readiness


def build_simulation_task(model_file: dict[str, Any], conditions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    readiness = check_simulation_readiness(model_file, conditions)
    return {
        "task_type": "simulation_preparation",
        "status": "stub_only",
        "simulation_ready": False,
        "model_file": dict(model_file or {}),
        "conditions": dict(conditions or {}),
        "readiness": readiness,
        "execution": {
            "will_run_cfd": False,
            "solver": None,
            "cfd_results": None,
        },
        "warnings": [
            "当前只生成仿真准备任务 JSON。",
            "当前不调用 ANSYS、Fluent、COMSOL 或其他 CFD 求解器。",
            "当前不生成压降、温度场、速度场或泵曲线结果。",
        ],
    }
