from __future__ import annotations

import json
from threading import Lock
from uuid import uuid4

from .config import ModelAssetConfig
from .sanitizer import sanitize_mapping
from .schemas import AuditEvent, utc_now_iso


_AUDIT_LOCK = Lock()
_ACTIONS = frozenset({"upload", "submit_review", "approve", "reject", "block", "register", "hash_mismatch", "archive"})
_ACTOR_TYPES = frozenset({"user", "operator", "system"})


class ModelAssetAuditLog:
    def __init__(self, config: ModelAssetConfig) -> None:
        self.config = config

    def append(
        self,
        *,
        action: str,
        asset_id: str,
        previous_status: str | None,
        new_status: str | None,
        actor_type: str,
        success: bool = True,
        reason: str = "",
    ) -> dict[str, object]:
        normalized_action = action if action in _ACTIONS else "block"
        normalized_actor = actor_type if actor_type in _ACTOR_TYPES else "system"
        sanitized_reason = str(sanitize_mapping(str(reason or "")))[:1000]
        event = AuditEvent(
            event_id=f"asset-event-{uuid4().hex}", timestamp=utc_now_iso(), action=normalized_action,
            asset_id=str(asset_id or ""), previous_status=previous_status, new_status=new_status,
            actor_type=normalized_actor, success=bool(success), reason=sanitized_reason,
        ).to_dict()
        path = self.config.audit_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event


__all__ = ["ModelAssetAuditLog"]
