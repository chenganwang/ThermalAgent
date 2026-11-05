from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from hashlib import sha256
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping

from .memory.reference_resolver import resolve_references as resolve_references_from_context


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dedupe(items: list[str], *, max_items: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = (item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if max_items is not None and len(out) >= max_items:
            break
    return out


def _session_identity(session_id: str) -> str:
    return (session_id or "default").strip() or "default"


def _safe_session_id(session_id: str) -> str:
    # The filename must not merge punctuation, Unicode, long identifiers or
    # case-distinct IDs on case-insensitive Windows filesystems.
    return "session_" + sha256(_session_identity(session_id).encode("utf-8")).hexdigest()


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    try:
        return asdict(value)
    except Exception:
        return {}


@dataclass
class ConversationTurn:
    user_query: str
    assistant_answer: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConversationMemory:
    """Small replaceable conversation memory for short-term agent state.

    The default local backend stores one JSON file per session. The class also
    supports an in-memory backend for tests and later replacement by a database.
    """

    def __init__(
        self,
        backend: str | None = None,
        memory_path: str | Path | None = None,
        max_turns: int = 8,
    ) -> None:
        self.backend = (backend or os.getenv("AGENT_MEMORY_BACKEND", "local")).lower()
        self.memory_path = Path(memory_path or os.getenv("AGENT_MEMORY_PATH", "./runtime/memory"))
        self.max_turns = int(max_turns)
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = RLock()
        if self.backend == "local":
            self.memory_path.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        return self.memory_path / f"{_safe_session_id(session_id)}.json"

    def _legacy_session_path(self, session_id: str) -> Path | None:
        # Only unambiguous legacy identifiers are eligible; ambiguous sanitized
        # files remain preserved for manual recovery, never silently shared.
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", session_id):
            return self.memory_path / f"{session_id}.json"
        return None

    def _empty_session(self, session_id: str) -> dict[str, Any]:
        return {
            "session_id": _session_identity(session_id),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "turns": [],
            "entities": [],
            "focus": None,
            "preferences": [],
            "last_task": None,
            "last_rewrite": None,
        }

    def _load(self, session_id: str) -> dict[str, Any]:
        sid = _session_identity(session_id)
        if sid in self._sessions:
            return deepcopy(self._sessions[sid])
        if self.backend == "local":
            paths = [self._session_path(sid), self._legacy_session_path(sid)]
            for path in paths:
                if path is None or not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("session_id") == sid:
                        self._sessions[sid] = data
                        return deepcopy(data)
                except Exception:
                    pass
        data = self._empty_session(sid)
        self._sessions[sid] = deepcopy(data)
        return data

    def _save(self, session_id: str, data: dict[str, Any]) -> None:
        sid = _session_identity(session_id)
        data["session_id"] = sid
        data["updated_at"] = _utc_now()
        if self.backend == "local":
            self.memory_path.mkdir(parents=True, exist_ok=True)
            path = self._session_path(sid)
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        self._sessions[sid] = deepcopy(data)

    def add_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            data = self._load(session_id)
            turns = list(data.get("turns") or [])
            turns.append(ConversationTurn(user_query=user_query, assistant_answer=assistant_answer, metadata=metadata or {}).to_dict())
            data["turns"] = turns[-self.max_turns :]
            self._save(session_id, data)

    def get_context(self, session_id: str, max_turns: int = 5) -> dict[str, Any]:
        with self._lock:
            data = self._load(session_id)
            context = deepcopy(data)
            context["turns"] = list(context.get("turns") or [])[-int(max_turns) :]
            return context

    def resolve_references(self, session_id: str, query: str) -> str:
        """Resolve common Chinese/English references using the current focus."""

        text = query or ""
        if not text.strip():
            return text
        context = self.get_context(session_id, max_turns=3)
        return resolve_references_from_context(text, context)

    def update_state(
        self,
        session_id: str,
        task_result: Any,
        rewrite_result: Any,
    ) -> None:
        with self._lock:
            data = self._load(session_id)
            task = _as_dict(task_result)
            rewrite = _as_dict(rewrite_result)
            entities = _dedupe(
                [
                    *list(data.get("entities") or []),
                    *[str(x) for x in task.get("entities", []) if x],
                    *[str(x) for x in rewrite.get("entities", []) if x],
                ],
                max_items=24,
            )
            data["entities"] = entities
            data["last_task"] = task
            data["last_rewrite"] = rewrite

            focus_candidates = [str(x) for x in rewrite.get("entities", []) if x] or [str(x) for x in task.get("entities", []) if x]
            if focus_candidates:
                data["focus"] = "、".join(focus_candidates[:3])

            keywords = [str(x) for x in rewrite.get("keywords", []) if x]
            if keywords:
                data["preferences"] = _dedupe([*list(data.get("preferences") or []), *keywords[:8]], max_items=32)
            self._save(session_id, data)

    def reset(self, session_id: str) -> None:
        with self._lock:
            sid = _session_identity(session_id)
            self._sessions.pop(sid, None)
            if self.backend == "local":
                path = self._session_path(sid)
                if path.exists():
                    path.unlink()
                legacy = self._legacy_session_path(sid)
                if legacy is not None and legacy.exists():
                    try:
                        data = json.loads(legacy.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        return
                    if isinstance(data, dict) and data.get('session_id') == sid:
                        legacy.unlink()
