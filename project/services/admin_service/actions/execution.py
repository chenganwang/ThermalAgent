from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Lock
from typing import Any

from pydantic import ValidationError

from services.admin_service.contracts import AdminAPIError

from .context import ActionExecutionContext
from .registry import ActionDescriptor
from .schemas import ActionHandlerResult


class ActionConcurrencyGuard:
    """Non-blocking, process-local per-action concurrency accounting."""

    def __init__(self) -> None:
        self._active: dict[str, int] = {}
        self._lock = Lock()

    def available(self, action_id: str, limit: int) -> bool:
        with self._lock:
            return self._active.get(action_id, 0) < limit

    def try_acquire(self, action_id: str, limit: int) -> bool:
        with self._lock:
            active = self._active.get(action_id, 0)
            if active >= limit:
                return False
            self._active[action_id] = active + 1
            return True

    def release(self, action_id: str) -> None:
        with self._lock:
            active = self._active.get(action_id, 0)
            if active <= 1:
                self._active.pop(action_id, None)
            else:
                self._active[action_id] = active - 1

    def reset_for_tests(self) -> None:
        with self._lock:
            self._active.clear()


class ActionExecutor:
    def __init__(
        self,
        *,
        guard: ActionConcurrencyGuard | None = None,
        max_workers: int = 4,
    ) -> None:
        self.guard = guard or ActionConcurrencyGuard()
        self._pool = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="admin-action")

    def execute(
        self,
        descriptor: ActionDescriptor,
        context: ActionExecutionContext,
        parameters: dict[str, Any],
    ) -> ActionHandlerResult:
        action_id = descriptor.action_id
        if not self.guard.try_acquire(action_id, descriptor.concurrency_limit):
            raise AdminAPIError(
                "ADMIN_ACTION_CONCURRENCY_LIMIT",
                "Action concurrency limit is currently reached.",
                status_code=429,
                retryable=True,
            )
        future = self._pool.submit(descriptor.handler, context, dict(parameters))
        released = False
        try:
            raw_result = future.result(timeout=descriptor.timeout_seconds)
        except FutureTimeoutError as exc:
            future.add_done_callback(lambda _future: self.guard.release(action_id))
            released = True
            raise AdminAPIError(
                "ADMIN_ACTION_TIMEOUT",
                "Action exceeded its server-defined time budget.",
                status_code=504,
                retryable=True,
            ) from exc
        except Exception as exc:
            raise AdminAPIError(
                "ADMIN_ACTION_EXECUTION_FAILED",
                "Action execution failed inside the isolated handler.",
                status_code=500,
            ) from exc
        finally:
            if not released and future.done():
                self.guard.release(action_id)
        try:
            if isinstance(raw_result, ActionHandlerResult):
                return raw_result
            return ActionHandlerResult.model_validate(raw_result, strict=True)
        except ValidationError as exc:
            raise AdminAPIError(
                "ADMIN_ACTION_EXECUTION_FAILED",
                "Action handler returned an invalid structured result.",
                status_code=500,
            ) from exc


__all__ = ["ActionConcurrencyGuard", "ActionExecutor"]
