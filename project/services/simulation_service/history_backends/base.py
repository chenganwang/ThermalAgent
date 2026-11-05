from __future__ import annotations

from abc import ABC, abstractmethod

from ..schema import SimulationHistoryRecord


class SimulationHistoryBackend(ABC):
    @abstractmethod
    def append(self, record: SimulationHistoryRecord | dict) -> SimulationHistoryRecord:
        raise NotImplementedError

    @abstractmethod
    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        tool_name: str | None = None,
        adapter_name: str | None = None,
        trace_id: str | None = None,
        is_mock: bool | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> list[SimulationHistoryRecord]:
        raise NotImplementedError

    @abstractmethod
    def get(self, history_id_or_run_id: str) -> SimulationHistoryRecord | None:
        raise NotImplementedError

    @abstractmethod
    def clear_for_test(self) -> None:
        raise NotImplementedError

    def health_check(self) -> dict[str, object]:
        return {"backend": "unknown", "available": True, "reason": "available"}


def coerce_history_record(record: SimulationHistoryRecord | dict) -> SimulationHistoryRecord:
    if isinstance(record, SimulationHistoryRecord):
        return record
    if isinstance(record, dict):
        try:
            return SimulationHistoryRecord(**record)
        except Exception as exc:
            raise ValueError(f"invalid simulation history record: {exc}") from exc
    raise ValueError(f"invalid simulation history record type: {type(record)!r}")


def filter_history_records(
    records: list[SimulationHistoryRecord],
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    tool_name: str | None = None,
    adapter_name: str | None = None,
    trace_id: str | None = None,
    is_mock: bool | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> list[SimulationHistoryRecord]:
    filtered = list(records)
    if status:
        filtered = [record for record in filtered if record.status == status]
    if tool_name:
        filtered = [
            record
            for record in filtered
            if record.result.get("tool_name") == tool_name
            or record.request.get("tool_name") == tool_name
            or record.metadata.get("tool_name") == tool_name
        ]
    if adapter_name:
        filtered = [
            record
            for record in filtered
            if record.result.get("adapter_name") == adapter_name
            or record.request.get("adapter_name") == adapter_name
            or record.metadata.get("adapter_name") == adapter_name
        ]
    if trace_id:
        filtered = [record for record in filtered if record.trace_id == trace_id or record.result.get("trace_id") == trace_id]
    if is_mock is not None:
        filtered = [record for record in filtered if bool(record.result.get("is_mock", record.result.get("mocked", False))) is bool(is_mock)]
    if created_after:
        filtered = [record for record in filtered if str(record.created_at) >= str(created_after)]
    if created_before:
        filtered = [record for record in filtered if str(record.created_at) <= str(created_before)]
    safe_offset = max(int(offset or 0), 0)
    safe_limit = max(min(int(limit or 50), 500), 0)
    return filtered[safe_offset : safe_offset + safe_limit]


__all__ = ["SimulationHistoryBackend", "coerce_history_record", "filter_history_records"]
