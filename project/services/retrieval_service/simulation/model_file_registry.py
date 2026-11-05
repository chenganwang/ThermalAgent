from __future__ import annotations

from pathlib import Path
from typing import Any


_EXTENSION_TYPES = {
    ".step": "STEP",
    ".stp": "STEP",
    ".stl": "STL",
    ".obj": "OBJ",
    ".fbx": "FBX",
    ".gltf": "GLTF",
    ".glb": "GLB",
    ".sldprt": "SLDPRT",
    ".sldasm": "SLDASM",
    ".iges": "IGES",
    ".igs": "IGES",
}

_REGISTERED_MODEL_FILES: dict[str, dict[str, Any]] = {}


def detect_model_file_type(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return _EXTENSION_TYPES.get(suffix, "UNKNOWN")


def _object_type(filename: str, description: str | None = None) -> str:
    text = f"{filename or ''} {description or ''}".lower()
    if any(term in text for term in ("cabinet", "rack", "机柜")):
        return "rack_cabinet"
    if any(term in text for term in ("server", "服务器")):
        return "server"
    if any(term in text for term in ("cold_plate", "cold plate", "冷板")):
        return "cold_plate"
    return "unspecified"


def register_model_file(file_id: str, filename: str, description: str | None = None) -> dict[str, Any]:
    normalized_id = str(file_id or "").strip()
    normalized_filename = str(filename or "").strip()
    if not normalized_id or not normalized_filename:
        raise ValueError("A real model file registration requires non-empty file_id and filename.")
    file_type = detect_model_file_type(filename)
    model_file = {
        "file_id": normalized_id,
        "filename": normalized_filename,
        "file_type": file_type,
        "object_type": _object_type(filename, description),
        "description": description,
        "usable_for": [
            "结构展示",
            "散热路径标注",
            "仿真准备",
        ],
        "not_yet_supported": [
            "自动网格划分",
            "CFD 求解",
            "压降计算",
            "泵曲线匹配",
        ],
        "warnings": [
            "当前仅登记模型文件元数据，不读取或修改模型文件。",
            "当前不运行 CFD，不输出仿真数值结果。",
        ],
    }
    _REGISTERED_MODEL_FILES[normalized_id] = dict(model_file)
    return dict(model_file)


def get_registered_model_file(file_id: str, filename: str | None = None) -> dict[str, Any] | None:
    normalized_id = str(file_id or "").strip()
    model_file = _REGISTERED_MODEL_FILES.get(normalized_id)
    if model_file is None:
        return None
    expected_filename = str(filename or "").strip()
    if expected_filename and expected_filename != str(model_file.get("filename") or ""):
        return None
    return dict(model_file)


def clear_registered_model_files() -> None:
    _REGISTERED_MODEL_FILES.clear()


__all__ = [
    "clear_registered_model_files",
    "detect_model_file_type",
    "get_registered_model_file",
    "register_model_file",
]
