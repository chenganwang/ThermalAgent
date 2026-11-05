from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BUILTIN_MODEL_CATALOG_PATH = Path(__file__).with_name("catalog") / "data" / "models.json"


def load_builtin_model_catalog(path: Path | None = None) -> dict[str, Any]:
    """Load the canonical built-in model identity catalog without importing adapters."""

    return json.loads((path or BUILTIN_MODEL_CATALOG_PATH).read_text(encoding="utf-8"))


def executable_matlab_dispatcher_ids(path: Path | None = None) -> frozenset[str]:
    payload = load_builtin_model_catalog(path)
    return frozenset(
        str(item["dispatcher_model_id"])
        for item in payload.get("models") or ()
        if item.get("backend") == "matlab"
        and item.get("supports_execution") is True
        and item.get("status") == "available"
        and item.get("dispatcher_model_id")
    )


__all__ = ["BUILTIN_MODEL_CATALOG_PATH", "executable_matlab_dispatcher_ids", "load_builtin_model_catalog"]
