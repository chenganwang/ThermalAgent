from __future__ import annotations

from typing import Any

from ..properties.aliases import normalize_fluid
from .hydraulic_calculators import GRAVITY_M_S2
from .hydraulic_contracts import PumpSelectionChecklistItem, PumpSelectionPreparationResult


def _item(
    item_id: str,
    name: str,
    status: str,
    detail: str,
    *,
    required: bool,
) -> dict[str, Any]:
    return PumpSelectionChecklistItem(
        item_id=item_id,
        name=name,
        status=status,
        detail=detail,
        required=required,
    ).to_dict()


def prepare_pump_selection(requirements: dict[str, Any] | None) -> PumpSelectionPreparationResult:
    """Prepare vendor-selection requirements without choosing a pump model."""

    data = dict(requirements or {})
    flow = data.get("flow_rate_lpm")
    head = data.get("required_head_m")
    pressure = data.get("pressure_drop_kpa")
    coolant = normalize_fluid(data.get("coolant"))
    density = data.get("density_kg_m3")
    temperature = data.get("temperature_c")
    safety_factor = data.get("safety_factor")

    warnings: list[str] = []
    if head is None and pressure is not None:
        if density is None and coolant == "water":
            density = 1000.0
            warnings.append("default_water_assumption: density_kg_m3=1000 used only to convert pressure drop to head.")
        if density is not None and float(density) > 0:
            head = float(pressure) * 1000.0 / (float(density) * GRAVITY_M_S2)

    missing_inputs: list[str] = []
    if flow is None:
        missing_inputs.append("flow_rate_lpm")
    if head is None and pressure is None:
        missing_inputs.append("required_head_m_or_pressure_drop_kpa")

    warnings.extend(
        [
            "pump_curve_missing: verify the required operating point against a vendor pump curve.",
            "npsh_not_evaluated: NPSH data was not supplied and no NPSH value was inferred.",
            "No pump model, efficiency, price, or vendor recommendation has been selected.",
        ]
    )
    checklist = [
        _item("target_flow", "Target flow rate", "ok" if flow is not None else "missing", "Provided." if flow is not None else "Required flow rate is missing.", required=True),
        _item("target_head", "Target pump head", "ok" if head is not None else "missing", "Provided or converted from pressure drop." if head is not None else "Head cannot be established yet.", required=True),
        _item("pressure_drop", "System pressure drop", "ok" if pressure is not None else "warning", "Provided." if pressure is not None else "Retain or verify system pressure-drop basis.", required=False),
        _item("coolant", "Coolant type", "ok" if coolant else "missing", f"Coolant: {coolant}." if coolant else "Coolant compatibility is unknown.", required=True),
        _item("coolant_temperature", "Coolant temperature", "ok" if temperature is not None else "missing", "Provided." if temperature is not None else "Temperature is required for compatibility and property checks.", required=True),
        _item("material_compatibility", "Compatible wetted materials", "missing", "Verify seals and wetted materials with the coolant.", required=True),
        _item("pump_curve", "Vendor pump curve", "missing", "No verified pump curve was parsed or used.", required=True),
        _item("operating_point", "Curve operating point", "missing", "Cannot verify an operating point without a pump curve.", required=True),
        _item("npsh", "NPSH check", "missing", "NPSH available/required data was not supplied.", required=True),
        _item("noise_redundancy", "Noise, redundancy, and design margin", "warning", "Define project-specific acoustic, redundancy, and margin requirements.", required=False),
        _item("series_parallel", "Series/parallel pump arrangement", "not_applicable", "Evaluate later if one verified pump curve cannot cover the duty point.", required=False),
    ]
    status = "missing_params" if missing_inputs else "ready_for_vendor_selection"
    return PumpSelectionPreparationResult(
        generated=True,
        status=status,
        required_flow_rate_lpm=float(flow) if flow is not None else None,
        required_head_m=round(float(head), 6) if head is not None else None,
        required_pressure_drop_kpa=float(pressure) if pressure is not None else None,
        safety_factor=float(safety_factor) if safety_factor is not None else None,
        recommended_selection_margin=(
            "Apply a project-approved margin and verify the resulting duty point on a vendor curve."
            if not missing_inputs
            else None
        ),
        selection_checklist=checklist,
        missing_inputs=missing_inputs,
        warnings=warnings,
        not_selected_reason="No verified vendor pump curve or NPSH data was evaluated; no pump model was selected.",
        pump_model_selected=False,
        pump_curve_used=False,
    )


__all__ = ["prepare_pump_selection"]
