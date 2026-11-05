from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping


FEATURE_FLAG_ENV_MAP: dict[str, str] = {
    "simulation_visible": "FEATURE_SIMULATION_VISIBLE",
    "simulation_enabled": "FEATURE_SIMULATION_ENABLED",
    "report_visible": "FEATURE_REPORT_VISIBLE",
    "report_enabled": "FEATURE_REPORT_ENABLED",
}
DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "simulation_visible": True,
    "simulation_enabled": False,
    "report_visible": True,
    "report_enabled": False,
}
FEATURE_FLAG_NAMES = tuple(FEATURE_FLAG_ENV_MAP.keys())
DEFAULT_RUNTIME_PATH = Path("runtime/config/feature_flags.json")
DEFAULT_AUDIT_PATH = Path("runtime/config/feature_flags_audit.jsonl")


class FeatureFlagValidationError(ValueError):
    pass


@dataclass(frozen=True)
class FeatureFlagState:
    env_defaults: dict[str, bool]
    runtime_override: dict[str, bool]
    effective_flags: dict[str, bool]
    runtime_override_loaded: bool
    runtime_override_valid: bool
    runtime_override_errors: list[str]
    updated_at: str | None

    def source_summary(self) -> dict[str, object]:
        return {
            "env_defaults_loaded": True,
            "runtime_override_loaded": self.runtime_override_loaded,
            "runtime_override_valid": self.runtime_override_valid,
            "runtime_override_errors": list(self.runtime_override_errors),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled", ""}:
        return False
    return default


def admin_feature_flags_enabled() -> bool:
    return env_flag("ADMIN_FEATURE_FLAGS_ENABLED", False)


def env_default_feature_flags() -> dict[str, bool]:
    return {
        name: env_flag(env_name, DEFAULT_FEATURE_FLAGS[name])
        for name, env_name in FEATURE_FLAG_ENV_MAP.items()
    }


def feature_flag_runtime_path(root: Path | None = None) -> Path:
    return _configured_path("FEATURE_FLAGS_RUNTIME_PATH", DEFAULT_RUNTIME_PATH, root=root)


def feature_flag_audit_path(root: Path | None = None) -> Path:
    return _configured_path("FEATURE_FLAGS_AUDIT_PATH", DEFAULT_AUDIT_PATH, root=root)


def load_feature_flag_state(root: Path | None = None) -> FeatureFlagState:
    defaults = env_default_feature_flags()
    runtime_path = feature_flag_runtime_path(root)
    override, loaded, valid, errors, updated_at = _read_runtime_override(runtime_path)
    effective = dict(defaults)
    effective.update(override)
    return FeatureFlagState(
        env_defaults=defaults,
        runtime_override=override,
        effective_flags=effective,
        runtime_override_loaded=loaded,
        runtime_override_valid=valid,
        runtime_override_errors=errors,
        updated_at=updated_at,
    )


def get_effective_feature_flags(root: Path | None = None) -> dict[str, bool]:
    return dict(load_feature_flag_state(root).effective_flags)


def feature_flags_status(root: Path | None = None) -> dict[str, object]:
    state = load_feature_flag_state(root)
    return {
        "feature_flags": dict(state.effective_flags),
        "source": state.source_summary(),
        "updated_at": state.updated_at,
    }


def update_feature_flags(
    updates: Mapping[str, object],
    *,
    root: Path | None = None,
    actor: str = "admin_api",
) -> dict[str, object]:
    validated = validate_feature_flag_updates(updates)
    state = load_feature_flag_state(root)
    next_flags = dict(state.effective_flags)
    next_flags.update(validated)
    write_runtime_feature_flags(next_flags, root=root)
    updated_state = load_feature_flag_state(root)
    append_feature_flag_audit(
        {
            "action": "patch",
            "actor": actor,
            "changed_fields": sorted(validated),
            "previous_flags": state.effective_flags,
            "new_flags": updated_state.effective_flags,
        },
        root=root,
    )
    return feature_flags_status(root)


def reset_feature_flags(*, root: Path | None = None, actor: str = "admin_api") -> dict[str, object]:
    state = load_feature_flag_state(root)
    remove_runtime_feature_flag_override(root=root)
    reset_state = load_feature_flag_state(root)
    append_feature_flag_audit(
        {
            "action": "reset",
            "actor": actor,
            "previous_flags": state.effective_flags,
            "new_flags": reset_state.effective_flags,
        },
        root=root,
    )
    return feature_flags_status(root)


def validate_feature_flag_updates(payload: Mapping[str, object]) -> dict[str, bool]:
    if not isinstance(payload, Mapping):
        raise FeatureFlagValidationError("Feature flag payload must be a JSON object.")
    unknown = sorted(str(key) for key in payload if str(key) not in FEATURE_FLAG_ENV_MAP)
    if unknown:
        raise FeatureFlagValidationError(f"Unknown feature flag fields: {', '.join(unknown)}")
    invalid_types = sorted(str(key) for key, value in payload.items() if type(value) is not bool)
    if invalid_types:
        raise FeatureFlagValidationError(f"Feature flag fields must be boolean: {', '.join(invalid_types)}")
    return {str(key): bool(value) for key, value in payload.items()}


def write_runtime_feature_flags(
    flags: Mapping[str, object],
    *,
    root: Path | None = None,
    require_complete: bool = True,
) -> None:
    """Atomically write a validated runtime override without adding an audit event."""

    validated = validate_feature_flag_updates(flags)
    if require_complete and set(validated) != set(FEATURE_FLAG_NAMES):
        raise FeatureFlagValidationError("Runtime feature flag snapshots must contain all registered fields.")
    runtime_path = feature_flag_runtime_path(root)
    _ensure_runtime_write_path(runtime_path, expected_suffix=".json")
    _write_runtime_flags(runtime_path, validated, require_complete=require_complete)


def remove_runtime_feature_flag_override(*, root: Path | None = None) -> None:
    """Remove only the controlled runtime override; environment defaults remain untouched."""

    runtime_path = feature_flag_runtime_path(root)
    _ensure_runtime_write_path(runtime_path, expected_suffix=".json")
    try:
        runtime_path.unlink(missing_ok=True)
    except OSError as exc:
        raise FeatureFlagValidationError("Runtime feature flag override could not be removed.") from exc


def append_feature_flag_audit(event: Mapping[str, object], *, root: Path | None = None) -> None:
    """Append a legacy-compatible feature flag audit record."""

    audit_path = feature_flag_audit_path(root)
    _ensure_runtime_write_path(audit_path, expected_suffix=".jsonl")
    _append_audit(audit_path, event)


def _configured_path(env_name: str, default: Path, *, root: Path | None = None) -> Path:
    base = root or project_root()
    configured = os.getenv(env_name)
    path = Path(configured) if configured else default
    if not path.is_absolute():
        path = base / path
    return path


def _ensure_runtime_write_path(path: Path, *, expected_suffix: str) -> None:
    if path.name in {".env", ".env.example"}:
        raise FeatureFlagValidationError("Runtime feature flag paths must not target .env files.")
    if path.suffix.lower() != expected_suffix:
        raise FeatureFlagValidationError(f"Runtime feature flag path must end with {expected_suffix}.")


def _read_runtime_override(path: Path) -> tuple[dict[str, bool], bool, bool, list[str], str | None]:
    if not path.exists():
        return {}, False, True, [], None
    errors: list[str] = []
    updated_at = _file_mtime_iso(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, True, False, [f"runtime_override_unreadable:{type(exc).__name__}"], updated_at
    if not isinstance(raw, dict):
        return {}, True, False, ["runtime_override_must_be_object"], updated_at
    override: dict[str, bool] = {}
    for key, value in raw.items():
        name = str(key)
        if name not in FEATURE_FLAG_ENV_MAP:
            errors.append(f"unknown_field:{name}")
            continue
        if type(value) is not bool:
            errors.append(f"non_boolean_field:{name}")
            continue
        override[name] = value
    return override, True, not errors, errors, updated_at


def _write_runtime_flags(
    path: Path,
    flags: Mapping[str, bool],
    *,
    require_complete: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if require_complete:
        ordered = {name: bool(flags[name]) for name in FEATURE_FLAG_NAMES}
    else:
        ordered = {name: bool(flags[name]) for name in FEATURE_FLAG_NAMES if name in flags}
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _append_audit(path: Path, event: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": utc_now_iso(), **dict(event)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _file_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


__all__ = [
    "DEFAULT_FEATURE_FLAGS",
    "FEATURE_FLAG_ENV_MAP",
    "FEATURE_FLAG_NAMES",
    "FeatureFlagValidationError",
    "FeatureFlagState",
    "admin_feature_flags_enabled",
    "append_feature_flag_audit",
    "env_default_feature_flags",
    "env_flag",
    "feature_flag_audit_path",
    "feature_flag_runtime_path",
    "feature_flags_status",
    "get_effective_feature_flags",
    "load_feature_flag_state",
    "remove_runtime_feature_flag_override",
    "reset_feature_flags",
    "update_feature_flags",
    "validate_feature_flag_updates",
    "write_runtime_feature_flags",
]
