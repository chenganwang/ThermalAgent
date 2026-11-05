from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class ActionExecutionContext:
    invocation_id: str
    action_id: str
    request_id: str
    actor_id: str
    deadline_monotonic: float

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline_monotonic - monotonic())

    def deadline_exceeded(self) -> bool:
        return self.remaining_seconds <= 0


__all__ = ["ActionExecutionContext"]
