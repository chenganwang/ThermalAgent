from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from math import isfinite
from typing import Any, Mapping

from .compiler import output_logger_name
from .model_ir import ModelIR
from .output_registry import OutputRegistry


@dataclass(frozen=True)
class SeriesSample:
    time_s: float
    value: float


@dataclass(frozen=True)
class GeneratedOutputValue:
    logical_output_id: str
    quantity: str
    unit: str
    status: str
    value: float | None = None
    series: tuple[SeriesSample, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "logical_output_id": self.logical_output_id,
            "quantity": self.quantity,
            "unit": self.unit,
            "status": self.status,
        }
        if self.value is not None:
            result["value"] = self.value
        if self.series:
            result["series"] = [asdict(item) for item in self.series]
        return result


@dataclass(frozen=True)
class GeneratedSimulationResult:
    model_id: str
    model_version: str
    artifact_id: str
    solver_status: str
    outputs: tuple[GeneratedOutputValue, ...]
    warnings: tuple[str, ...]
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "artifact_id": self.artifact_id,
            "solver_status": self.solver_status,
            "outputs": [item.to_dict() for item in self.outputs],
            "warnings": list(self.warnings),
            "duration_seconds": self.duration_seconds,
        }


class GeneratedResultExtractor:
    """Extract only server-declared outputs from an opaque MATLAB result."""

    def __init__(
        self,
        *,
        output_registry: OutputRegistry | None = None,
        max_result_bytes: int = 131_072,
        max_raw_samples: int = 10_000,
    ) -> None:
        self.output_registry = output_registry or OutputRegistry.default()
        self.max_result_bytes = max(int(max_result_bytes), 1)
        self.max_raw_samples = max(int(max_raw_samples), 1)

    def extract(
        self,
        raw_result: object,
        *,
        model_ir: ModelIR,
        artifact_id: str,
        duration_seconds: float,
    ) -> GeneratedSimulationResult:
        outputs: list[GeneratedOutputValue] = []
        warnings: list[str] = []
        for requested in model_ir.requested_outputs:
            spec = self.output_registry.require(requested.type)
            logger_name = output_logger_name(model_ir.digest(), requested.id, requested.type)
            present, raw_value = _expected_value(raw_result, logger_name)
            if not present:
                outputs.append(GeneratedOutputValue(
                    requested.id, spec.quantity, spec.canonical_unit, "missing",
                ))
                warnings.append(f"EXPECTED_OUTPUT_MISSING:{requested.id}")
                continue
            series_values = _series_data(raw_value)
            if series_values is not None:
                times, values = series_values
                if len(times) > self.max_raw_samples or len(values) > self.max_raw_samples:
                    outputs.append(GeneratedOutputValue(
                        requested.id, spec.quantity, spec.canonical_unit, "invalid",
                    ))
                    warnings.append(f"OUTPUT_SERIES_LIMIT_EXCEEDED:{requested.id}")
                    continue
                if not times or len(times) != len(values):
                    outputs.append(GeneratedOutputValue(
                        requested.id, spec.quantity, spec.canonical_unit, "invalid",
                    ))
                    warnings.append(f"OUTPUT_VALUE_INVALID:{requested.id}")
                    continue
                if any(not isfinite(item) for item in (*times, *values)):
                    outputs.append(GeneratedOutputValue(
                        requested.id, spec.quantity, spec.canonical_unit, "non_finite",
                    ))
                    warnings.append(f"OUTPUT_NON_FINITE:{requested.id}")
                    continue
                indices = _bounded_indices(len(times), spec.max_samples)
                series = tuple(SeriesSample(times[index], values[index]) for index in indices)
                if len(indices) < len(times):
                    warnings.append(f"OUTPUT_SERIES_DOWNSAMPLED:{requested.id}")
                outputs.append(GeneratedOutputValue(
                    requested.id,
                    spec.quantity,
                    spec.canonical_unit,
                    "ok",
                    series=series,
                ))
                continue
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                outputs.append(GeneratedOutputValue(
                    requested.id, spec.quantity, spec.canonical_unit, "invalid",
                ))
                warnings.append(f"OUTPUT_VALUE_INVALID:{requested.id}")
                continue
            numeric = float(raw_value)
            if not isfinite(numeric):
                outputs.append(GeneratedOutputValue(
                    requested.id, spec.quantity, spec.canonical_unit, "non_finite",
                ))
                warnings.append(f"OUTPUT_NON_FINITE:{requested.id}")
                continue
            outputs.append(GeneratedOutputValue(
                requested.id,
                spec.quantity,
                spec.canonical_unit,
                "ok",
                value=numeric,
            ))
        result = GeneratedSimulationResult(
            model_id=model_ir.model_id,
            model_version=model_ir.schema_version,
            artifact_id=str(artifact_id),
            solver_status="completed",
            outputs=tuple(outputs),
            warnings=tuple(warnings),
            duration_seconds=float(duration_seconds),
        )
        encoded_size = len(
            json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if encoded_size > self.max_result_bytes:
            bounded_outputs = tuple(
                GeneratedOutputValue(
                    item.logical_output_id, item.quantity, item.unit, "invalid",
                ) if item.series else item
                for item in result.outputs
            )
            bounded_warnings = list(result.warnings)
            bounded_warnings.extend(
                f"OUTPUT_RESULT_BYTE_LIMIT:{item.logical_output_id}"
                for item in result.outputs
                if item.series
            )
            result = GeneratedSimulationResult(
                model_id=result.model_id,
                model_version=result.model_version,
                artifact_id=result.artifact_id,
                solver_status=result.solver_status,
                outputs=bounded_outputs,
                warnings=tuple(bounded_warnings),
                duration_seconds=result.duration_seconds,
            )
        return result


def _expected_value(raw_result: object, logger_name: str) -> tuple[bool, Any]:
    if isinstance(raw_result, Mapping):
        return (logger_name in raw_result, raw_result.get(logger_name))
    getter = getattr(raw_result, "get", None)
    if callable(getter):
        try:
            return True, getter(logger_name)
        except (KeyError, AttributeError, TypeError, ValueError):
            return False, None
    return False, None


def _series_data(raw_value: object) -> tuple[list[float], list[float]] | None:
    time_value = _member(raw_value, "time", "Time")
    signals = _member(raw_value, "signals", "Signals")
    data_value = _member(raw_value, "Data", "data")
    if signals is not None:
        data_value = _member(signals, "values", "Values")
    if time_value is None or data_value is None:
        return None
    times = _flatten_numbers(time_value)
    values = _flatten_numbers(data_value)
    return times, values


def _member(value: object, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        try:
            member = getattr(value, name)
        except (AttributeError, TypeError):
            continue
        if not callable(member):
            return member
    return None


def _flatten_numbers(value: object) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, (str, bytes, Mapping)):
        return []
    result: list[float] = []
    try:
        for item in value:  # type: ignore[union-attr]
            result.extend(_flatten_numbers(item))
    except TypeError:
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            pass
    return result


def _bounded_indices(length: int, limit: int) -> list[int]:
    if length <= limit:
        return list(range(length))
    if limit <= 1:
        return [length - 1]
    return [round(index * (length - 1) / (limit - 1)) for index in range(limit)]


__all__ = [
    "GeneratedOutputValue", "GeneratedResultExtractor", "GeneratedSimulationResult", "SeriesSample",
]
