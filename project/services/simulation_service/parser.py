from __future__ import annotations

import math
from typing import Any

from .contracts import SimulationAdapterResult, SimulationResultEnvelope, SimulationRunRequest
from .schema import utc_now_iso


PARSER_VERSION = "simulation-parser-v1"


class SimulationResultParser:
    """Normalize adapter output into the stable SimulationResultEnvelope contract."""

    def parse(
        self,
        *,
        request: SimulationRunRequest,
        adapter_result: SimulationAdapterResult,
        task_id: str,
        job_id: str | None,
        history_id: str | None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        elapsed_ms: int | None = None,
    ) -> SimulationResultEnvelope:
        raw = _sanitize(dict(adapter_result.raw_result or {}))
        result = {
            "values": _dict(raw.get("values")),
            "vectors": _dict(raw.get("vectors")),
            "tables": _list(raw.get("tables")),
            "series": _list(raw.get("series")),
            "timeseries": _list(raw.get("timeseries")),
            "figure_paths": _list(raw.get("figure_paths")),
            "raw_json": _dict(raw.get("raw_json")),
            "summary": _dict(raw.get("summary")),
        }
        merged_metadata = {
            "parser_version": PARSER_VERSION,
            "adapter_metadata": dict(adapter_result.metadata or {}),
            "cfd_executed": False,
            "solver_executed": False,
        }
        if metadata:
            merged_metadata.update(metadata)
        return SimulationResultEnvelope(
            task_id=task_id,
            job_id=job_id,
            tool_name=request.tool_name,
            adapter_name=adapter_result.adapter_name,
            status=adapter_result.status,
            mocked=adapter_result.mocked,
            inputs=dict(request.inputs or {}),
            result=result,
            artifacts=list(adapter_result.artifacts or []),
            warnings=_unique([*(warnings or []), *adapter_result.warnings]),
            errors=list(adapter_result.errors or []),
            history_id=history_id,
            metadata=merged_metadata,
            run_id=run_id,
            backend_type=adapter_result.backend_type or adapter_result.adapter_name,
            units=dict(getattr(request, "units", {}) or {}),
            raw_output=_dict(adapter_result.raw_output) or raw,
            started_at=started_at,
            finished_at=finished_at or utc_now_iso(),
            elapsed_ms=elapsed_ms if elapsed_ms is not None else adapter_result.elapsed_ms,
            trace_id=getattr(request, "trace_id", None),
            is_mock=adapter_result.mocked,
            software=adapter_result.software or adapter_result.adapter_name,
            software_version=adapter_result.software_version,
        )


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _sanitize(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


__all__ = ["PARSER_VERSION", "SimulationResultParser"]
