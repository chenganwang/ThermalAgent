from __future__ import annotations

from .base import SimulationHistoryBackend, coerce_history_record, filter_history_records
from ..schema import SimulationHistoryRecord


class MemoryHistoryBackend(SimulationHistoryBackend):
    def __init__(self) -> None:
        self._records: list[SimulationHistoryRecord] = []

    def append(self, record: SimulationHistoryRecord | dict) -> SimulationHistoryRecord:
        item = coerce_history_record(record)
        self._records.append(item)
        return item

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
        return filter_history_records(
            self._records,
            limit=limit,
            offset=offset,
            status=status,
            tool_name=tool_name,
            adapter_name=adapter_name,
            trace_id=trace_id,
            is_mock=is_mock,
            created_after=created_after,
            created_before=created_before,
        )

    def get(self, history_id_or_run_id: str) -> SimulationHistoryRecord | None:
        for record in self._records:
            if record.history_id == history_id_or_run_id or record.run_id == history_id_or_run_id:
                return record
        return None

    def clear_for_test(self) -> None:
        self._records.clear()

    def health_check(self) -> dict[str, object]:
        return {"backend": "memory", "available": True, "reason": "available"}


__all__ = ["MemoryHistoryBackend"]
