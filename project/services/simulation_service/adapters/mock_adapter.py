from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import SimulationAdapter
from ..contracts import (
    SIMULATION_STATUS_FAILED,
    SIMULATION_STATUS_SUCCESS,
    SIMULATION_STATUS_TIMEOUT,
    SimulationAdapterResult,
    SimulationRunRequest,
    SimulationToolSpec,
)


class MockAdapter(SimulationAdapter):
    name = "mock"
    software = "mock"
    backend_type = "mock"
    _SUPPORTED_TOOLS = {
        "matlab_function_eval",
        "liquid_cooling_temp_rise_mock",
        "thermal_network_solve_mock",
    }

    def capabilities(self) -> dict[str, object]:
        return {
            "tools": sorted(self._SUPPORTED_TOOLS),
            "mock": True,
            "real_backend": False,
            "requires_external_software": False,
            "external_software_name": None,
            "modes": ["success", "failure", "timeout", "invalid_parameters", "golden_fixture"],
        }

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._SUPPORTED_TOOLS

    def run(self, request: SimulationRunRequest, spec: SimulationToolSpec) -> SimulationAdapterResult:
        options = _merged_config(request)
        mock_mode = str(options.get("mock_mode") or "success").strip().lower()
        if mock_mode == "failure":
            return _mock_error(
                spec,
                code="mock_forced_failure",
                message="Mock Adapter forced failure mode was requested.",
            )
        if mock_mode == "timeout":
            return _mock_error(
                spec,
                code="simulation_timeout",
                message="Mock Adapter deterministic timeout mode was requested.",
                status=SIMULATION_STATUS_TIMEOUT,
            )
        if mock_mode == "invalid_parameters":
            return _mock_error(
                spec,
                code="simulation_validation_error",
                message="Mock Adapter deterministic invalid-parameters mode was requested.",
            )
        if mock_mode == "golden_fixture":
            return self._fixture_result(request, spec, str(options.get("fixture_name") or ""))

        inputs = dict(request.inputs or {})
        if spec.tool_name == "liquid_cooling_temp_rise_mock":
            raw_result = self._liquid_cooling_temp_rise(inputs)
        elif spec.tool_name == "thermal_network_solve_mock":
            raw_result = self._thermal_network_solve(inputs)
        else:
            function_name = str(inputs.get("function_name") or "mock_function")
            parameters = dict(inputs.get("parameters") or {})
            raw_result = self._mock_function_result(function_name, parameters)
        return SimulationAdapterResult(
            tool_name=spec.tool_name,
            adapter_name=self.name,
            status=SIMULATION_STATUS_SUCCESS,
            mocked=True,
            raw_result=raw_result,
            warnings=["mock_result_not_real_solver_output"],
            backend_type=self.backend_type,
            software=self.software,
            metadata={
                "function_name": str(inputs.get("function_name") or spec.tool_name),
                "cfd_executed": False,
                "solver_executed": False,
                "real_engine_used": False,
                "mock_mode": mock_mode,
            },
        )

    def _mock_function_result(self, function_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if function_name == "estimate_temperature":
            power = _number(parameters, "power_w", "P_W", "q_w")
            resistance = _number(parameters, "r_k_per_w", "R_total_K_per_W", "thermal_resistance_k_per_w")
            inlet = _number(parameters, "t_in_c", "T_in_C", "inlet_temperature_c")
            if power is not None and resistance is not None and inlet is not None:
                rise = power * resistance
                temperature = inlet + rise
                return {
                    "values": {
                        "junction_temperature_c": {"value": round(temperature, 6), "unit": "degC"},
                        "temperature_rise_k": {"value": round(rise, 6), "unit": "K"},
                    },
                    "tables": [],
                    "series": [],
                    "summary": {
                        "function_name": function_name,
                        "formula": "T_j_C = t_in_c + power_w * r_k_per_w",
                    },
                }
        return {
            "values": {
                "mock_value": {"value": 0.0, "unit": "dimensionless"},
            },
            "tables": [],
            "series": [],
            "summary": {
                "function_name": function_name,
                "note": "Generic deterministic mock response.",
            },
        }

    def _liquid_cooling_temp_rise(self, inputs: dict[str, Any]) -> dict[str, Any]:
        heat_load = _number(inputs, "heat_load_w", "Q_W")
        mass_flow = _number(inputs, "mass_flow_kg_s", "m_dot_kg_s")
        cp = _number(inputs, "cp_j_kgk", "cp_J_kgK")
        inlet = _number(inputs, "inlet_temperature_c", "T_in_C")
        if heat_load is None or mass_flow in (None, 0) or cp in (None, 0):
            return {"values": {}, "tables": [], "series": [], "summary": {"status": "missing_params"}}
        rise = heat_load / (mass_flow * cp)
        values = {"coolant_temperature_rise_k": {"value": round(rise, 6), "unit": "K"}}
        if inlet is not None:
            outlet = {"value": round(inlet + rise, 6), "unit": "degC"}
            values["coolant_outlet_temperature_c"] = outlet
            values["outlet_temperature_c"] = outlet
        return {
            "values": values,
            "tables": [],
            "series": [],
            "summary": {"formula": "delta_T_K = Q_W / (m_dot_kg_s * cp_J_kgK)"},
        }

    def _thermal_network_solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        heat_load = _number(inputs, "heat_load_w", "Q_W") or 0.0
        reference = _number(inputs, "reference_temperature_c", "T_ref_C") or 0.0
        resistances = inputs.get("resistances_k_per_w") or []
        try:
            total = sum(float(item) for item in resistances)
        except (TypeError, ValueError):
            total = 0.0
        junction = reference + heat_load * total
        return {
            "values": {
                "total_resistance_k_per_w": {"value": round(total, 6), "unit": "K/W"},
                "junction_temperature_c": {"value": round(junction, 6), "unit": "degC"},
            },
            "tables": [],
            "series": [],
            "summary": {"formula": "T_j_C = T_ref_C + Q_W * sum(R_i)"},
        }

    def _fixture_result(self, request: SimulationRunRequest, spec: SimulationToolSpec, fixture_name: str) -> SimulationAdapterResult:
        fixture = _load_fixture(fixture_name)
        if not fixture:
            return _mock_error(spec, code="mock_fixture_not_found", message=f"Mock fixture not found: {fixture_name}")
        subset = dict(fixture.get("expected_subset") or {})
        raw_result = {
            "values": {},
            "tables": [],
            "series": [],
            "summary": {"fixture_name": fixture_name},
        }
        for key, value in subset.items():
            parts = str(key).split(".")
            if len(parts) == 4 and parts[0] == "result" and parts[1] == "values":
                raw_result["values"].setdefault(parts[2], {})[parts[3]] = value
        warnings = list(fixture.get("required_warnings") or ["mock_result_not_real_solver_output"])
        return SimulationAdapterResult(
            tool_name=spec.tool_name,
            adapter_name=self.name,
            status=SIMULATION_STATUS_SUCCESS,
            mocked=True,
            raw_result=raw_result,
            warnings=warnings,
            backend_type=self.backend_type,
            software=self.software,
            metadata={
                "fixture_name": fixture_name,
                "mock_mode": "golden_fixture",
                "cfd_executed": False,
                "solver_executed": False,
                "real_engine_used": False,
            },
        )


def _number(values: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = values.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _merged_config(request: SimulationRunRequest) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if isinstance(request.config, dict):
        config.update(request.config)
    inputs_config = (request.inputs or {}).get("config")
    if isinstance(inputs_config, dict):
        config.update(inputs_config)
    config.update(request.options or {})
    return config


def _mock_error(
    spec: SimulationToolSpec,
    *,
    code: str,
    message: str,
    status: str = SIMULATION_STATUS_FAILED,
) -> SimulationAdapterResult:
    return SimulationAdapterResult(
        tool_name=spec.tool_name,
        adapter_name="mock",
        status=status,
        mocked=True,
        raw_result={},
        warnings=["mock_result_not_real_solver_output"],
        errors=[{"code": code, "message": message}],
        backend_type="mock",
        software="mock",
        metadata={
            "cfd_executed": False,
            "solver_executed": False,
            "real_engine_used": False,
        },
    )


def _load_fixture(fixture_name: str) -> dict[str, Any] | None:
    if not fixture_name:
        return None
    safe = Path(fixture_name).stem
    path = Path(__file__).resolve().parents[3] / "docs" / "simulation" / "fixtures" / f"{safe}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["MockAdapter"]
