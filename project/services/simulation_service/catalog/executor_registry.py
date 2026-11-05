from __future__ import annotations

import json
from math import log, pi
from pathlib import Path
from typing import Any, Callable

from ..matlab.adapter import MatlabSimulationAdapter
from .schemas import CatalogConfigurationError, ExecutorDefinition, ModelDefinition


class SimulationExecutor:
    """Controlled executor interface; callers never supply an entrypoint."""

    def __init__(self, definition: ExecutorDefinition) -> None:
        self.definition = definition

    def status(self) -> dict[str, Any]:
        return self.definition.to_dict()

    def validate(self, model: ModelDefinition, params: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(params) - set(model.allowed_inputs))
        return {"valid": not unknown, "unknown_parameters": unknown}

    def plan(self, model: ModelDefinition, params: dict[str, Any]) -> dict[str, Any]:
        validation = self.validate(model, params)
        return {
            **validation,
            "executor_id": self.definition.executor_id,
            "solver": self.definition.solver,
            "entrypoint_id": self.definition.entrypoint_id,
        }

    def run(self, model: ModelDefinition, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MatlabSimulationExecutor(SimulationExecutor):
    def __init__(self, definition: ExecutorDefinition, adapter_factory: Callable[[], MatlabSimulationAdapter]) -> None:
        super().__init__(definition)
        self._adapter_factory = adapter_factory

    def run(self, model: ModelDefinition, params: dict[str, Any]) -> dict[str, Any]:
        validation = self.validate(model, params)
        if not validation["valid"]:
            raise CatalogConfigurationError("MATLAB model received inputs outside its registry allowlist")
        if model.entrypoint_id != "heat_conduction_1d" or self.definition.entrypoint_id != "heat_conduction_1d":
            raise CatalogConfigurationError("MATLAB model entrypoint is not a registered controlled demo")
        result = self._adapter_factory().run_demo("heat_conduction_1d", dict(params), require_api_enabled=True)
        payload = result.to_dict()
        if payload.get("success"):
            outputs = dict(payload.get("outputs") or {})
            delta = float(params["t_hot_c"]) - float(params["t_cold_c"])
            outputs.update({"temperature_difference_k": delta, "heat_flux_w_m2": float(outputs["heat_rate_w"]) / float(params["area_m2"])})
            payload["outputs"] = outputs
            payload["units"] = {**dict(payload.get("units") or {}), "temperature_difference_k": "K", "heat_flux_w_m2": "W/m2"}
        return payload


class PythonSimulationExecutor(SimulationExecutor):
    def __init__(self, definition: ExecutorDefinition, runner: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        super().__init__(definition)
        self._runner = runner

    def run(self, model: ModelDefinition, params: dict[str, Any]) -> dict[str, Any]:
        validation = self.validate(model, params)
        if not validation["valid"]:
            raise CatalogConfigurationError("Python model received inputs outside its registry allowlist")
        return dict(self._runner(dict(params)))


class ExecutorRegistry:
    def __init__(self, data_path: Path | None = None, *, matlab_adapter_factory: Callable[[], MatlabSimulationAdapter] | None = None) -> None:
        path = data_path or Path(__file__).with_name("data") / "executors.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.registry_version = str(raw.get("registry_version") or "unknown")
        self._items = {x.executor_id: x for x in (ExecutorDefinition.from_dict(item) for item in raw.get("executors") or ())}
        adapter_factory = matlab_adapter_factory or MatlabSimulationAdapter
        python_runners = {
            "python_controlled_executor:cylindrical_wall_v1": _cylindrical,
            "python_controlled_executor:multilayer_wall_v1": _multilayer,
            "python_controlled_executor:liquid_loop_energy_balance_v1": _liquid_loop,
            "python_controlled_executor:junction_temperature_network_v1": _junction_network,
        }
        self._executors: dict[str, SimulationExecutor] = {
            "matlab_controlled_adapter:heat_conduction_1d": MatlabSimulationExecutor(
                self._items["matlab_controlled_adapter:heat_conduction_1d"],
                adapter_factory,
            ),
            **{
                executor_id: PythonSimulationExecutor(self._items[executor_id], runner)
                for executor_id, runner in python_runners.items()
            },
        }
        if set(self._items) != set(self._executors):
            raise CatalogConfigurationError("executor metadata and controlled runner registry differ")

    def list(self) -> list[ExecutorDefinition]:
        return list(self._items.values())

    def get(self, executor_id: str) -> ExecutorDefinition | None:
        return self._items.get(executor_id)

    def for_model(self, model: ModelDefinition) -> ExecutorDefinition | None:
        if not model.adapter_id or not model.entrypoint_id:
            return None
        return self.get(f"{model.adapter_id}:{model.entrypoint_id}")

    def run(self, model: ModelDefinition, params: dict[str, Any]) -> dict[str, Any]:
        executor = self.for_model(model)
        if executor is None or executor.status != "available":
            raise CatalogConfigurationError(f"controlled executor unavailable: {model.model_id}")
        return self._executors[executor.executor_id].run(model, params)


def _success(outputs: dict[str, Any], units: dict[str, str], formula: str, assumptions: list[str]) -> dict[str, Any]:
    return {"success": True, "status": "success", "outputs": outputs, "units": units, "formula": formula, "assumptions": assumptions, "warnings": []}


def _cylindrical(p: dict[str, Any]) -> dict[str, Any]:
    delta = p["t_inner_c"] - p["t_outer_c"]
    resistance = log(p["outer_radius_m"] / p["inner_radius_m"]) / (2 * pi * p["thermal_conductivity_w_mk"] * p["length_m"])
    return _success({"temperature_difference_k": delta, "heat_rate_w": delta / resistance, "thermal_resistance_k_w": resistance}, {"temperature_difference_k": "K", "heat_rate_w": "W", "thermal_resistance_k_w": "K/W"}, "Q_dot = 2*pi*k*L*(T_inner-T_outer)/ln(r_outer/r_inner)", ["一维径向稳态导热", "导热系数恒定"])


def _multilayer(p: dict[str, Any]) -> dict[str, Any]:
    resistances = [x["thickness_m"] / (x["thermal_conductivity_w_mk"] * p["area_m2"]) for x in p["layers"]]
    total = sum(resistances)
    heat = (p["t_hot_c"] - p["t_cold_c"]) / total
    drops = [{"name": layer["name"], "temperature_drop_k": heat * resistance} for layer, resistance in zip(p["layers"], resistances)]
    return _success({"total_thermal_resistance_k_w": total, "heat_rate_w": heat, "layer_temperature_drops": drops}, {"total_thermal_resistance_k_w": "K/W", "heat_rate_w": "W", "layer_temperature_drops": "K"}, "R_total = sum(L_i/(k_i*A)); Q_dot = DeltaT/R_total", ["串联一维稳态导热"])


def _liquid_loop(p: dict[str, Any]) -> dict[str, Any]:
    heat, cp, inlet = p["heat_load_w"], p["specific_heat_j_kgk"], p["inlet_temperature_c"]
    if "mass_flow_kg_s" in p:
        mass_flow = p["mass_flow_kg_s"]
        rise = heat / (mass_flow * cp)
    elif "allowed_temperature_rise_k" in p:
        rise = p["allowed_temperature_rise_k"]
        mass_flow = heat / (cp * rise)
    else:
        rise = p["outlet_temperature_c"] - inlet
        mass_flow = heat / (cp * rise)
    return _success({"mass_flow_kg_s": mass_flow, "temperature_rise_k": rise, "outlet_temperature_c": inlet + rise, "heat_load_w": heat}, {"mass_flow_kg_s": "kg/s", "temperature_rise_k": "K", "outlet_temperature_c": "degC", "heat_load_w": "W"}, "Q = m_dot*cp*DeltaT", ["稳态能量平衡", "比热容恒定"])


def _junction_network(p: dict[str, Any]) -> dict[str, Any]:
    total = sum(x["value"] for x in p["thermal_resistances_k_w"])
    temperature = p["ambient_temperature_c"]
    nodes = [{"name": "ambient", "temperature_c": temperature}]
    for resistance in reversed(p["thermal_resistances_k_w"]):
        temperature += p["power_w"] * resistance["value"]
        nodes.append({"name": resistance["name"], "temperature_c": temperature})
    return _success({"total_thermal_resistance_k_w": total, "junction_temperature_c": p["ambient_temperature_c"] + p["power_w"] * total, "node_temperatures_c": nodes}, {"total_thermal_resistance_k_w": "K/W", "junction_temperature_c": "degC", "node_temperatures_c": "degC"}, "T_j = T_ambient + P*sum(R)", ["所有热阻串联且稳态"])


__all__ = ["ExecutorRegistry", "MatlabSimulationExecutor", "PythonSimulationExecutor", "SimulationExecutor"]
