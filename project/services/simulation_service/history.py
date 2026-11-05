from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .contracts import SimulationHistoryEvent, SimulationRunRequest


class InMemorySimulationHistoryRepository:
    """In-memory Phase 1 history repository for tests and no-database baseline."""

    def __init__(self) -> None:
        self._tasks: dict[str, SimulationRunRequest] = {}
        self._jobs: dict[str, dict[str, Any]] = {}
        self._events: list[SimulationHistoryEvent] = []

    def create_task(self, request: SimulationRunRequest) -> str:
        task_id = _id("sim-task")
        self._tasks[task_id] = request
        self._record(task_id=task_id, job_id=None, event_type="task_created", payload=request.to_dict())
        return task_id

    def start_job(self, *, task_id: str, adapter_name: str) -> str:
        job_id = _id("sim-job")
        self._jobs[job_id] = {
            "job_id": job_id,
            "task_id": task_id,
            "adapter_name": adapter_name,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "result": None,
        }
        self._record(task_id=task_id, job_id=job_id, event_type="job_started", payload={"adapter_name": adapter_name})
        return job_id

    def finish_job(self, *, task_id: str, job_id: str, status: str, result: dict[str, Any]) -> str:
        job = self._jobs.setdefault(job_id, {"job_id": job_id, "task_id": task_id})
        job["status"] = status
        job["finished_at"] = _now()
        job["result"] = result
        event = self._record(
            task_id=task_id,
            job_id=job_id,
            event_type="job_finished",
            payload={"status": status, "result": result},
        )
        return event.history_id

    def list_events(self, task_id: str | None = None) -> list[SimulationHistoryEvent]:
        if task_id is None:
            return list(self._events)
        return [event for event in self._events if event.task_id == task_id]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        request = self._tasks.get(task_id)
        if request is None:
            return None
        return {"task_id": task_id, "request": request.to_dict()}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        return dict(job) if job is not None else None

    def replay_task(self, task_id: str) -> SimulationRunRequest:
        request = self._tasks.get(task_id)
        if request is None:
            raise KeyError(f"Unknown simulation task: {task_id}")
        return request

    def _record(self, *, task_id: str, job_id: str | None, event_type: str, payload: dict[str, Any]) -> SimulationHistoryEvent:
        event = SimulationHistoryEvent(
            history_id=_id("sim-history"),
            task_id=task_id,
            job_id=job_id,
            event_type=event_type,
            actor="simulation_service",
            payload=dict(payload),
            created_at=_now(),
        )
        self._events.append(event)
        return event


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["InMemorySimulationHistoryRepository"]
