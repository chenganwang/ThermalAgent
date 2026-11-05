from __future__ import annotations

from typing import Any, Mapping

from .model_file_registry import detect_model_file_type, get_registered_model_file, register_model_file
from .simulation_readiness_checker import check_simulation_readiness
from .simulation_task_schema import build_simulation_task


def prepare_simulation_stub(
    *,
    file_id: str,
    filename: str,
    description: str | None = None,
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    model_file = get_registered_model_file(file_id, filename)
    if model_file is None:
        return missing_model_file_payload()
    readiness = check_simulation_readiness(model_file, conditions)
    task = build_simulation_task(model_file, conditions)
    return {
        "enabled": True,
        "status": "stub_only",
        "stage": "simulation_preparation_stub",
        "simulation_ready": False,
        "cfd_executed": False,
        "model_file": model_file,
        "readiness": readiness,
        "task": task,
        "message": "已使用登记模型创建 CFD 仿真准备任务；当前不会运行 CFD。",
    }


def missing_model_file_payload() -> dict[str, Any]:
    return {
        "enabled": True,
        "status": "missing_model_file",
        "stage": "simulation_preparation_blocked",
        "simulation_ready": False,
        "model_file": None,
        "missing_inputs": ["model_file"],
        "readiness": {
            "simulation_ready": False,
            "model_file": None,
            "missing_conditions": ["model_file"],
            "stage": "simulation_preparation_blocked",
        },
        "task": None,
        "cfd_executed": False,
        "message": "尚未上传或选择模型文件。",
    }


__all__ = [
    "build_simulation_task",
    "check_simulation_readiness",
    "detect_model_file_type",
    "missing_model_file_payload",
    "prepare_simulation_stub",
    "register_model_file",
]
