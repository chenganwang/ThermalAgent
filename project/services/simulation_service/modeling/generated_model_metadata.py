from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Mapping


GENERATED_MODEL_ORIGINS = frozenset({"admin_uploaded", "llm_generated"})
GENERATED_MODEL_RETENTIONS = frozenset({"ephemeral", "resident"})
DEFAULT_EPHEMERAL_TTL_SECONDS = 7 * 24 * 60 * 60

_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]+")
_SPACE = re.compile(r"\s+")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_after(value: datetime, seconds: int) -> str:
    return (value + timedelta(seconds=max(0, int(seconds)))).isoformat()


def normalize_origin(value: Any) -> str:
    origin = str(value or "").strip().casefold()
    return origin if origin in GENERATED_MODEL_ORIGINS else "llm_generated"


def normalize_retention(value: Any, *, origin: str) -> str:
    retention = str(value or "").strip().casefold()
    if retention in GENERATED_MODEL_RETENTIONS:
        return retention
    return "resident" if normalize_origin(origin) == "admin_uploaded" else "ephemeral"


def sanitize_display_name(value: Any) -> str:
    name = _SPACE.sub(" ", _UNSAFE_NAME.sub(" ", str(value or ""))).strip(" .-_；;，,")
    if len(name) < 2:
        raise ValueError("Generated-model display name must contain at least 2 safe characters.")
    return name[:40].rstrip()


def derive_display_name(model_ir: Mapping[str, Any] | None) -> str:
    facts = model_facts(model_ir)
    domain = "稳态热网络" if facts["domain"] == "thermal" else (facts["domain"] or "工程模型")
    branch_count = facts["parallel_branch_count"]
    topology = f"{branch_count}支路并联" if branch_count >= 2 else "串联"
    return sanitize_display_name(f"{domain} · {topology} · {facts['component_count']}组件")


def derive_model_summary(model_ir: Mapping[str, Any] | None) -> str:
    facts = model_facts(model_ir)
    domain = "热网络" if facts["domain"] == "thermal" else (facts["domain"] or "未知域")
    topology = f"{facts['parallel_branch_count']} 条并联支路" if facts["parallel_branch_count"] >= 2 else "串联拓扑"
    types = "、".join(facts["component_types"][:5]) or "无组件"
    return f"{domain}；{topology}；{facts['component_count']} 个组件、{facts['connection_count']} 条连接；组件类型：{types}。"


def model_facts(model_ir: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = model_ir if isinstance(model_ir, Mapping) else {}
    components = [item for item in (raw.get("components") or []) if isinstance(item, Mapping)]
    connections = [item for item in (raw.get("connections") or []) if isinstance(item, Mapping)]
    types = list(dict.fromkeys(str(item.get("type") or "") for item in components if item.get("type")))
    branch_ids = {
        str(item.get("id") or "")
        for item in components
        if re.search(r"(?:^|_)branch(?:_|$)", str(item.get("id") or ""), re.IGNORECASE)
    }
    resistance_branches = {
        item for item in branch_ids
        if any(component.get("id") == item and component.get("type") == "thermal_resistance" for component in components)
    }
    return {
        "domain": str(raw.get("model_domain") or ""),
        "model_id": str(raw.get("model_id") or ""),
        "component_count": len(components),
        "connection_count": len(connections),
        "component_types": types,
        "parallel_branch_count": len(resistance_branches),
        "requested_output_count": len([item for item in (raw.get("requested_outputs") or []) if isinstance(item, Mapping)]),
    }


def capability_signature(model_ir: Mapping[str, Any] | None) -> str | None:
    """Canonical reusable capability identity; display names and prompt wording are excluded."""
    raw = model_ir if isinstance(model_ir, Mapping) else {}
    if not raw:
        return None
    facts = model_facts(raw)
    components = [item for item in (raw.get("components") or []) if isinstance(item, Mapping)]
    type_counts: dict[str, int] = {}
    for component in components:
        component_type = str(component.get("type") or "")
        if component_type:
            type_counts[component_type] = type_counts.get(component_type, 0) + 1
    outputs = sorted(
        {
            str(item.get("type") or "")
            for item in (raw.get("requested_outputs") or [])
            if isinstance(item, Mapping) and item.get("type")
        }
    )
    contract = {
        "domain": facts["domain"],
        "topology": "parallel" if facts["parallel_branch_count"] >= 2 else "series",
        "parallel_branch_count": facts["parallel_branch_count"],
        "component_type_counts": sorted(type_counts.items()),
        "requested_output_types": outputs,
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_EPHEMERAL_TTL_SECONDS", "GENERATED_MODEL_ORIGINS", "GENERATED_MODEL_RETENTIONS",
    "capability_signature", "derive_display_name", "derive_model_summary", "iso_after", "model_facts",
    "normalize_origin", "normalize_retention", "sanitize_display_name", "utc_now",
]
