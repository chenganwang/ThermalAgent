from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigDefinition:
    key: str
    display_name: str
    description: str
    affected_modules: tuple[str, ...]
    category: str = "feature_flags"
    value_type: str = "boolean"
    sensitive: bool = False
    read_only: bool = False
    online_mutable: bool = True
    effective_immediately: bool = True
    requires_reload: bool = False
    requires_restart: bool = False
    risk_level: str = "medium"
    required_read_permission: str = "config.read"
    required_write_permission: str = "config.write"

    def schema(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "category": self.category,
            "type": self.value_type,
            "sensitive": self.sensitive,
            "read_only": self.read_only,
            "online_mutable": self.online_mutable,
            "effective_immediately": self.effective_immediately,
            "requires_reload": self.requires_reload,
            "requires_restart": self.requires_restart,
            "risk_level": self.risk_level,
            "affected_modules": list(self.affected_modules),
            "required_read_permission": self.required_read_permission,
            "required_write_permission": self.required_write_permission,
            "description": self.description,
        }


CONFIG_DEFINITIONS = (
    ConfigDefinition(
        key="simulation_visible",
        display_name="显示仿真模块",
        description="控制普通前端是否显示仿真入口；不授予执行权限。",
        affected_modules=("simulation_service",),
    ),
    ConfigDefinition(
        key="simulation_enabled",
        display_name="允许仿真交互",
        description="表达前端启用意图；MATLAB、模型和执行器后端门禁仍然独立生效。",
        affected_modules=("simulation_service", "matlab"),
    ),
    ConfigDefinition(
        key="report_visible",
        display_name="显示报告模块",
        description="控制普通前端是否显示报告入口。",
        affected_modules=("report_service",),
    ),
    ConfigDefinition(
        key="report_enabled",
        display_name="允许报告交互",
        description="表达前端启用意图；报告 inventory 与现有生成能力门禁仍然独立生效。",
        affected_modules=("report_service",),
    ),
)
CONFIG_REGISTRY = {item.key: item for item in CONFIG_DEFINITIONS}
CONFIG_KEYS = tuple(item.key for item in CONFIG_DEFINITIONS)


def registered_config_schema() -> list[dict[str, Any]]:
    return [item.schema() for item in CONFIG_DEFINITIONS]


__all__ = [
    "CONFIG_DEFINITIONS",
    "CONFIG_KEYS",
    "CONFIG_REGISTRY",
    "ConfigDefinition",
    "registered_config_schema",
]
