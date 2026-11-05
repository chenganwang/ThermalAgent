from __future__ import annotations

from collections import Counter
from typing import Iterable

from .checkers import SafeCheckRunner, build_module_descriptors
from .contracts import AdminAPIError, AdminCheckContext, ModuleDescriptor, ModuleHealth


class ModuleRegistry:
    def __init__(
        self,
        descriptors: Iterable[ModuleDescriptor] | None = None,
        *,
        runner: SafeCheckRunner | None = None,
    ) -> None:
        items = tuple(descriptors or build_module_descriptors())
        by_id = {item.module_id: item for item in items}
        if len(by_id) != len(items):
            raise ValueError("Duplicate Admin module_id")
        self._ordered = items
        self._by_id = by_id
        self.runner = runner or SafeCheckRunner()

    def descriptors(self) -> tuple[ModuleDescriptor, ...]:
        return self._ordered

    def require(self, module_id: str) -> ModuleDescriptor:
        descriptor = self._by_id.get(str(module_id or ""))
        if descriptor is None:
            raise AdminAPIError(
                "MODULE_NOT_FOUND",
                "Module is not registered.",
                status_code=404,
                details={"module_id": str(module_id or "")},
            )
        return descriptor

    def list_health(self, context: AdminCheckContext, *, force: bool = False) -> list[ModuleHealth]:
        return self.runner.check_all(self._ordered, context, force=force)

    def check(self, module_id: str, context: AdminCheckContext, *, force: bool = False) -> ModuleHealth:
        return self.runner.check(self.require(module_id), context, force=force)

    @staticmethod
    def summarize(items: Iterable[ModuleHealth]) -> dict[str, object]:
        health = list(items)
        counts = Counter(item.status for item in health)
        overall = aggregate_overall_status(health)
        return {
            "overall_status": overall,
            "counts": {
                key: counts.get(key, 0)
                for key in ("healthy", "degraded", "unhealthy", "disabled", "unavailable", "unknown", "checking")
            },
            "total": len(health),
        }


def aggregate_overall_status(items: Iterable[ModuleHealth]) -> dict[str, str]:
    modules = list(items)
    required = [item for item in modules if not item.optional and item.status != "disabled"]
    optional = [item for item in modules if item.optional and item.status != "disabled"]
    if any(item.status in {"unhealthy", "unavailable"} for item in required):
        return {"status": "unhealthy", "severity": "critical", "message": "A required module is unavailable or unhealthy."}
    if any(item.status in {"degraded", "unknown", "checking"} for item in required):
        return {"status": "degraded", "severity": "warning", "message": "One or more required modules are degraded or not fully checked."}
    if any(item.status in {"unhealthy", "unavailable", "degraded", "unknown", "checking"} for item in optional):
        return {"status": "degraded", "severity": "warning", "message": "Core modules are available, but an optional module is degraded or not fully checked."}
    return {"status": "healthy", "severity": "info", "message": "All enabled registered modules passed their bounded checks."}


__all__ = ["ModuleRegistry", "aggregate_overall_status"]
