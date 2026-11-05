from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .registry import CONFIG_KEYS, CONFIG_REGISTRY


def build_config_diff(
    previous: Mapping[str, bool],
    proposed: Mapping[str, bool],
) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "previous_value": bool(previous[key]),
            "new_value": bool(proposed[key]),
            "changed": True,
            "risk_level": CONFIG_REGISTRY[key].risk_level,
            "affected_modules": list(CONFIG_REGISTRY[key].affected_modules),
        }
        for key in CONFIG_KEYS
        if bool(previous[key]) != bool(proposed[key])
    ]


def affected_modules(diff: list[dict[str, Any]]) -> list[str]:
    modules = {
        str(module)
        for item in diff
        for module in item.get("affected_modules") or ()
    }
    return sorted(modules)


__all__ = ["affected_modules", "build_config_diff"]
