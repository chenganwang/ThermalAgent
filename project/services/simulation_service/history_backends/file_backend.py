from __future__ import annotations

from pathlib import Path
import json

from .base import SimulationHistoryBackend, coerce_history_record, filter_history_records
from ..schema import SimulationHistoryRecord, model_to_dict


class FileHistoryBackend(SimulationHistoryBackend):
    def __init__(self, history_dir: Path) -> None:
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.history_dir / "simulation_history.jsonl"

    def append(self, record: SimulationHistoryRecord | dict) -> SimulationHistoryRecord:
        item = coerce_history_record(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(model_to_dict(item), ensure_ascii=False, sort_keys=True) + "\n")
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
            self._load(),
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
        for record in self._load():
            if record.history_id == history_id_or_run_id or record.run_id == history_id_or_run_id:
                return record
        return None

    def clear_for_test(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def health_check(self) -> dict[str, object]:
        return {
            "backend": "file",
            "available": True,
            "reason": "available",
            "path": str(self.path),
        }

    def _load(self) -> list[SimulationHistoryRecord]:
        if not self.path.exists():
            return []
        records: list[SimulationHistoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(coerce_history_record(json.loads(line)))
        return records


__all__ = ["FileHistoryBackend"]
