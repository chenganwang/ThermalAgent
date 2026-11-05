from __future__ import annotations

from copy import deepcopy
from typing import Any

from .thermal_network_calculators import solve_thermal_resistance_network
from .thermal_network_contracts import ThermalSensitivityPlan


def _missing_plan(missing: list[str], perturbation: dict[str, Any] | None = None) -> ThermalSensitivityPlan:
    return ThermalSensitivityPlan(
        generated=True,
        status="missing_params",
        base_metric="junction_temperature_c",
        target_metric="junction_temperature_c",
        perturbations=[deepcopy(perturbation or {})] if perturbation else [],
        expected_outputs=["what_if_junction_temperature_c", "delta_temperature_c"],
        missing_inputs=list(dict.fromkeys(missing)),
        warnings=["sensitivity_preparation_only_not_optimization"],
    )


def prepare_thermal_sensitivity(
    network: dict[str, Any] | None,
    perturbation: dict[str, Any] | None = None,
) -> ThermalSensitivityPlan:
    base_network = deepcopy(network or {})
    change = deepcopy(perturbation or {})
    if not base_network:
        return _missing_plan(["base_network"], change)
    if not change:
        return ThermalSensitivityPlan(
            generated=True,
            status="ready",
            base_metric="junction_temperature_c",
            target_metric="junction_temperature_c",
            parameters=list(base_network.get("elements") or []),
            perturbations=[],
            expected_outputs=["what_if_junction_temperature_c", "delta_temperature_c"],
            missing_inputs=["perturbation"],
            warnings=["define_one_explicit_parameter_perturbation", "sensitivity_preparation_only_not_optimization"],
        )

    element_id = str(change.get("element_id") or "")
    elements = list(base_network.get("elements") or [])
    target = next((row for row in elements if str(row.get("element_id") or "") == element_id), None)
    if target is None:
        return _missing_plan(["perturbation.element_id_present_in_base_network"], change)
    parameter = str(change.get("parameter") or "")
    what_if = deepcopy(base_network)
    what_if_target = next(row for row in what_if.get("elements") or [] if str(row.get("element_id") or "") == element_id)
    missing: list[str] = []

    if parameter == "resistance_k_per_w":
        base_resistance = target.get("resistance_k_per_w")
        if base_resistance is None:
            missing.append(f"{element_id}.resistance_k_per_w")
        elif change.get("reduction_percent") is not None:
            percent = float(change["reduction_percent"])
            if percent < 0 or percent >= 100:
                return ThermalSensitivityPlan(generated=True, status="unsupported", perturbations=[change], warnings=["reduction_percent_must_be_between_0_and_100"], cfd_executed=False)
            what_if_target["resistance_k_per_w"] = float(base_resistance) * (1.0 - percent / 100.0)
        elif change.get("to") is not None:
            what_if_target["resistance_k_per_w"] = float(change["to"])
        else:
            missing.append("perturbation.reduction_percent_or_to")

    elif parameter == "thermal_conductivity_w_mk":
        for field in ("thickness_m", "area_m2"):
            if target.get(field) is None:
                missing.append(f"{element_id}.{field}")
        if change.get("to") is None:
            missing.append("perturbation.to")
        if not missing:
            what_if_target["thermal_conductivity_w_mk"] = float(change["to"])
            what_if_target.pop("resistance_k_per_w", None)

    elif parameter == "heat_transfer_coefficient_w_m2k":
        if target.get("area_m2") is None:
            missing.append(f"{element_id}.area_m2")
        base_h = target.get("heat_transfer_coefficient_w_m2k")
        if base_h is None:
            missing.append(f"{element_id}.heat_transfer_coefficient_w_m2k")
        if not missing:
            if change.get("increase_percent") is not None:
                what_if_target["heat_transfer_coefficient_w_m2k"] = float(base_h) * (1.0 + float(change["increase_percent"]) / 100.0)
            elif change.get("to") is not None:
                what_if_target["heat_transfer_coefficient_w_m2k"] = float(change["to"])
            else:
                missing.append("perturbation.increase_percent_or_to")
            what_if_target.pop("resistance_k_per_w", None)
    else:
        return ThermalSensitivityPlan(generated=True, status="unsupported", perturbations=[change], warnings=["unsupported_sensitivity_parameter"], cfd_executed=False)

    if missing:
        return _missing_plan(missing, change)
    base_result = solve_thermal_resistance_network(base_network)
    what_if_result = solve_thermal_resistance_network(what_if)
    if base_result.status != "success" or what_if_result.status != "success":
        combined = list(base_result.missing_parameters) + list(what_if_result.missing_parameters)
        return _missing_plan(combined or ["solvable_base_and_what_if_network"], change)
    base_t = base_result.junction_temperature_c
    what_if_t = what_if_result.junction_temperature_c
    if base_t is None or what_if_t is None:
        return _missing_plan(["heat_load_w", "reference_temperature_c"], change)
    return ThermalSensitivityPlan(
        generated=True,
        status="computed",
        base_metric="junction_temperature_c",
        target_metric="junction_temperature_c",
        base_junction_temperature_c=base_t,
        what_if_junction_temperature_c=what_if_t,
        delta_temperature_c=what_if_t - base_t,
        parameters=[deepcopy(target)],
        perturbations=[change],
        expected_outputs=["what_if_junction_temperature_c", "delta_temperature_c"],
        missing_inputs=[],
        warnings=["what_if_engineering_estimate_not_optimization_or_cfd"],
    )


__all__ = ["prepare_thermal_sensitivity"]
