from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from services.simulation_service.feature_flags import (
    FeatureFlagState,
    append_feature_flag_audit,
    feature_flags_status,
    load_feature_flag_state,
    remove_runtime_feature_flag_override,
    write_runtime_feature_flags,
)


@dataclass(frozen=True)
class FeatureFlagCapture:
    env_defaults: dict[str, bool]
    runtime_override: dict[str, bool]
    effective_flags: dict[str, bool]
    runtime_override_loaded: bool
    runtime_override_valid: bool
    runtime_override_errors: tuple[str, ...]
    updated_at: str | None


class FeatureFlagConfigAdapter:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def capture(self) -> FeatureFlagCapture:
        state: FeatureFlagState = load_feature_flag_state(self.project_root)
        return FeatureFlagCapture(
            env_defaults=dict(state.env_defaults),
            runtime_override=dict(state.runtime_override),
            effective_flags=dict(state.effective_flags),
            runtime_override_loaded=state.runtime_override_loaded,
            runtime_override_valid=state.runtime_override_valid,
            runtime_override_errors=tuple(state.runtime_override_errors),
            updated_at=state.updated_at,
        )

    def write_snapshot(self, snapshot: Mapping[str, object]) -> None:
        write_runtime_feature_flags(snapshot, root=self.project_root, require_complete=True)

    def reset_to_environment(self) -> None:
        remove_runtime_feature_flag_override(root=self.project_root)

    def restore(self, capture: FeatureFlagCapture) -> None:
        if capture.runtime_override_loaded:
            write_runtime_feature_flags(
                capture.runtime_override,
                root=self.project_root,
                require_complete=False,
            )
        else:
            remove_runtime_feature_flag_override(root=self.project_root)

    def append_legacy_audit(self, event: Mapping[str, object]) -> None:
        append_feature_flag_audit(event, root=self.project_root)

    def legacy_status(self) -> dict[str, object]:
        return feature_flags_status(self.project_root)


__all__ = ["FeatureFlagCapture", "FeatureFlagConfigAdapter"]
