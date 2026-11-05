from __future__ import annotations

from pathlib import Path
from typing import Any


class MemoryService:
    """Thin service wrapper around the legacy-compatible ConversationMemory."""

    def __init__(self, backend: str | None = None, memory_path: str | Path | None = None, max_turns: int = 8) -> None:
        from ..conversation_memory import ConversationMemory

        self.store = ConversationMemory(backend=backend, memory_path=memory_path, max_turns=max_turns)

    def add_turn(self, session_id: str, user_query: str, assistant_answer: str, metadata: dict[str, Any] | None = None) -> None:
        self.store.add_turn(session_id, user_query, assistant_answer, metadata)

    def get_context(self, session_id: str, max_turns: int = 5) -> dict[str, Any]:
        return self.store.get_context(session_id, max_turns=max_turns)

    def resolve_references(self, session_id: str, query: str) -> str:
        return self.store.resolve_references(session_id, query)

    def update_state(self, session_id: str, task_result: Any, rewrite_result: Any) -> None:
        self.store.update_state(session_id, task_result, rewrite_result)

    def reset(self, session_id: str) -> None:
        self.store.reset(session_id)
