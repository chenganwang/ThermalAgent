from __future__ import annotations

from collections import Counter
from typing import Iterable

from .contracts import ToolSpec
from .specs import ALL_TOOL_SPECS, TOOL_EXECUTORS, ToolFunc


class ToolRegistry:
    """Read-only registry for declarative ToolSpec definitions."""

    def __init__(
        self,
        specs: Iterable[ToolSpec] | None = None,
        *,
        executor_map: dict[str, ToolFunc] | None = None,
    ) -> None:
        self._items = list(specs or [])
        self._specs = {spec.name: spec for spec in self._items if spec.name}
        self._executor_map = dict(executor_map or TOOL_EXECUTORS)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"Unknown tool: {name}")
        return spec

    def list(self) -> list[ToolSpec]:
        return list(self._items)

    def names(self) -> list[str]:
        return [spec.name for spec in self._items]

    def find_by_domain(self, domain: str) -> list[ToolSpec]:
        return [spec for spec in self._items if spec.domain == domain]

    def get_executor(self, executor: str) -> ToolFunc | None:
        return self._executor_map.get(executor)

    def validate(self) -> list[str]:
        errors: list[str] = []
        names = [spec.name for spec in self._items]
        for name, count in Counter(names).items():
            if name and count > 1:
                errors.append(f"duplicate tool name: {name}")

        for index, spec in enumerate(self._items):
            label = spec.name or f"<index {index}>"
            if not spec.name:
                errors.append(f"{label}: name must not be empty")
            if not isinstance(spec.required_params, list):
                errors.append(f"{label}: required_params must be a list")
            if not spec.formula:
                errors.append(f"{label}: formula must not be empty")
            if not spec.executor:
                errors.append(f"{label}: executor must not be empty")
            elif spec.executor not in self._executor_map:
                errors.append(f"{label}: executor is not mapped: {spec.executor}")
            if not isinstance(spec.output_fields, list):
                errors.append(f"{label}: output_fields must be a list")
            if not spec.intent_keywords:
                errors.append(f"{label}: intent_keywords must not be empty")
        return errors


DEFAULT_TOOL_REGISTRY = ToolRegistry(ALL_TOOL_SPECS, executor_map=TOOL_EXECUTORS)


__all__ = ["DEFAULT_TOOL_REGISTRY", "ToolRegistry"]
