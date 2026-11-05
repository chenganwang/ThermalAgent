from __future__ import annotations

from functools import wraps
from inspect import signature
from math import isfinite
from typing import Any

from services.physics_service import PhysicsValidationRequest, validate_physics


CalculationResult = dict[str, Any]

_POSITIVE_OUTPUT_FIELDS = {
    "R_required_K_per_W", "allowed_delta_T_K", "temperature_rise_K",
    "R_cond_K_per_W", "delta_T_K", "heat_rate_W", "heat_flux_W_m2",
    "mass_flow_kg_s", "volume_flow_m3_s", "volume_flow_L_min",
}


def _json_safe_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Do not echo NaN/Infinity into FastAPI's strict JSON serializer."""
    def safe(value: Any) -> Any:
        if isinstance(value, float) and not isfinite(value):
            return None
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [safe(item) for item in value]
        return value

    return {name: safe(value) for name, value in inputs.items()}


def _validated_calculation(function):
    """One numeric boundary for the six scalar thermal calculators.

    Existing formulas and valid results remain unchanged. Non-numeric inputs,
    impossible absolute temperatures, and arithmetic overflow fail explicitly.
    """
    call_signature = signature(function)

    @wraps(function)
    def checked(*args, **kwargs):
        bound = call_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        inputs = dict(bound.arguments)
        errors = []
        for name, value in inputs.items():
            if name in {"material_name", "fluid_name"}:
                continue
            if value is None:
                if call_signature.parameters[name].default is not None:
                    errors.append(f"{name} must be a finite number")
                continue
            try:
                number = float(value)
                if isinstance(value, bool) or not isfinite(number):
                    raise ValueError
                if name.endswith("_C") and name != "safety_margin_C" and number < -273.15:
                    errors.append(f"{name} must be >= -273.15 degC")
                if name == "safety_margin_C" and number < 0:
                    errors.append("safety_margin_C must be >= 0")
            except (TypeError, ValueError, OverflowError):
                errors.append(f"{name} must be a finite number (boolean values are not accepted)")
        if errors:
            return _error_result(function.__name__, inputs=inputs, formula="", message="; ".join(errors), engineering_note="Input validation failed; no numerical estimate was produced.")
        try:
            result = function(*args, **kwargs)
        except ArithmeticError:
            return _error_result(function.__name__, inputs=inputs, formula="", message="Numerical range exceeded; check input magnitudes and units.", engineering_note="No reliable numerical estimate was produced.")
        invalid_output = any(
            isinstance(value, (int, float)) and (
                not isfinite(value) or (name in _POSITIVE_OUTPUT_FIELDS and value <= 0)
            )
            for name, value in result.get("result", {}).items()
        )
        if result.get("status") == "ok" and invalid_output:
            result.update(status="error", result={}, error="Calculation produced a non-finite or non-positive physical result; check input magnitudes and units.")
            result["unit_check"] = {"status": "failed", "messages": [result["error"]]}
        return result

    return checked


def _round_value(value: float | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    rounded = round(numeric, 6)
    # Preserve a small nonzero physical quantity instead of presenting it as 0.
    return numeric if numeric != 0 and rounded == 0 else rounded


def _base_result(
    tool_name: str,
    *,
    inputs: dict[str, Any],
    formula: str,
    engineering_note: str,
    assumptions: list[str] | None = None,
) -> CalculationResult:
    return {
        "tool_name": tool_name,
        "status": "ok",
        "inputs": _json_safe_inputs(inputs),
        "formula": formula,
        "calculation_steps": [],
        "result": {},
        "unit_check": {
            "status": "passed",
            "messages": [],
        },
        "warnings": [],
        "assumptions": list(assumptions or []),
        "engineering_note": engineering_note,
        "error": None,
    }


def _error_result(
    tool_name: str,
    *,
    inputs: dict[str, Any],
    formula: str,
    message: str,
    engineering_note: str,
    assumptions: list[str] | None = None,
    unit_messages: list[str] | None = None,
) -> CalculationResult:
    return {
        "tool_name": tool_name,
        "status": "error",
        "inputs": _json_safe_inputs(inputs),
        "formula": formula,
        "calculation_steps": [],
        "result": {},
        "unit_check": {
            "status": "failed",
            "messages": list(unit_messages or [message]),
        },
        "warnings": [],
        "assumptions": list(assumptions or []),
        "engineering_note": engineering_note,
        "error": message,
    }


def _positive_errors(values: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name, value in values.items():
        try:
            if value is None or float(value) <= 0:
                errors.append(f"{name} must be > 0")
        except (TypeError, ValueError):
            errors.append(f"{name} must be a number > 0")
    return errors


def mm_to_m(value_mm: float) -> float:
    return float(value_mm) / 1000.0


def mm2_to_m2(value_mm2: float) -> float:
    return float(value_mm2) * 1e-6


def cm2_to_m2(value_cm2: float) -> float:
    return float(value_cm2) * 1e-4


def l_min_to_m3_s(value_l_min: float) -> float:
    return float(value_l_min) / 60000.0


def m3_s_to_l_min(value_m3_s: float) -> float:
    return float(value_m3_s) * 60000.0


def kg_s_to_l_min_given_density(m_dot_kg_s: float, rho_kg_m3: float) -> float:
    return m3_s_to_l_min(float(m_dot_kg_s) / float(rho_kg_m3))


@_validated_calculation
def required_thermal_resistance(
    *,
    P_W: float,
    T_max_C: float,
    T_in_C: float,
    safety_margin_C: float = 0.0,
) -> CalculationResult:
    """Calculate the maximum allowed total thermal resistance."""

    formula = "R_required = (T_max_C - safety_margin_C - T_in_C) / P_W"
    note = (
        "This is a total thermal-resistance target estimate. It does not split package, "
        "TIM/contact, cold-plate, convection, coolant-loop, or facility-side resistance."
    )
    inputs = {
        "P_W": P_W,
        "T_max_C": T_max_C,
        "T_in_C": T_in_C,
        "safety_margin_C": safety_margin_C,
    }
    errors = _positive_errors({"P_W": P_W})
    if errors:
        return _error_result(
            "required_thermal_resistance",
            inputs=inputs,
            formula=formula,
            message="; ".join(errors),
            engineering_note=note,
        )
    allowed_delta = float(T_max_C) - float(safety_margin_C) - float(T_in_C)
    if allowed_delta <= 0:
        return _error_result(
            "required_thermal_resistance",
            inputs=inputs,
            formula=formula,
            message="T_max_C - safety_margin_C must be greater than T_in_C",
            engineering_note=note,
        )

    result = _base_result("required_thermal_resistance", inputs=inputs, formula=formula, engineering_note=note)
    r_required = allowed_delta / float(P_W)
    result["calculation_steps"] = [
        f"Allowed temperature rise = {T_max_C} - {safety_margin_C} - {T_in_C} = {_round_value(allowed_delta)} K",
        f"R_required = {_round_value(allowed_delta)} / {P_W} = {_round_value(r_required)} K/W",
    ]
    result["result"] = {
        "R_required_K_per_W": _round_value(r_required),
        "allowed_delta_T_K": _round_value(allowed_delta),
    }
    result["unit_check"]["messages"].append("W, degC temperature difference, and K/W are dimensionally consistent.")
    if r_required < 0.02:
        result["warnings"].append(
            "The required total thermal resistance is very low; verify cold plate, TIM, flow rate, and test/CFD evidence."
        )
    result["warnings"].append(note)
    return result


@_validated_calculation
def junction_temperature_estimate(
    *,
    P_W: float,
    T_in_C: float,
    R_total_K_per_W: float,
    T_limit_C: float | None = None,
) -> CalculationResult:
    """Estimate junction or heat-source temperature from total thermal resistance."""

    formula = "T_j_C = T_in_C + P_W * R_total_K_per_W"
    note = (
        "This linear total-resistance model is for first-pass estimates only. It omits dynamic power, "
        "hot spots, flow distribution, package spreading, and non-uniform cold-plate heat transfer."
    )
    inputs = {
        "P_W": P_W,
        "T_in_C": T_in_C,
        "R_total_K_per_W": R_total_K_per_W,
        "T_limit_C": T_limit_C,
    }
    errors = _positive_errors({"P_W": P_W, "R_total_K_per_W": R_total_K_per_W})
    if errors:
        return _error_result(
            "junction_temperature_estimate",
            inputs=inputs,
            formula=formula,
            message="; ".join(errors),
            engineering_note=note,
        )

    temperature_rise = float(P_W) * float(R_total_K_per_W)
    t_j = float(T_in_C) + temperature_rise
    margin = None if T_limit_C is None else float(T_limit_C) - t_j
    result = _base_result("junction_temperature_estimate", inputs=inputs, formula=formula, engineering_note=note)
    result["calculation_steps"] = [
        f"Temperature rise = {P_W} * {R_total_K_per_W} = {_round_value(temperature_rise)} K",
        f"T_j = {T_in_C} + {_round_value(temperature_rise)} = {_round_value(t_j)} degC",
    ]
    result["result"] = {
        "T_j_C": _round_value(t_j),
        "temperature_rise_K": _round_value(temperature_rise),
        "margin_to_limit_C": _round_value(margin),
    }
    result["unit_check"]["messages"].append("W multiplied by K/W gives K, then added to degC reference temperature.")
    if T_limit_C is not None and t_j > float(T_limit_C):
        result["warnings"].append("Estimated temperature exceeds the provided limit.")
    if temperature_rise > 80:
        result["warnings"].append("Temperature rise is high; check the thermal path and cooling capacity.")
    result["warnings"].append(note)
    return result


@_validated_calculation
def conduction_resistance(
    *,
    L_m: float,
    k_W_mK: float,
    A_m2: float,
    material_name: str | None = None,
    heat_load_W: float | None = None,
) -> CalculationResult:
    """Calculate one-dimensional steady conduction resistance."""

    formula = "R_cond = L_m / (k_W_mK * A_m2)"
    note = (
        "This is a one-dimensional steady conduction approximation. It does not include contact resistance, "
        "interface pressure, aging, non-uniform heat flux, or multidimensional spreading."
    )
    inputs = {
        "L_m": L_m,
        "k_W_mK": k_W_mK,
        "A_m2": A_m2,
        "material_name": material_name,
        "heat_load_W": heat_load_W,
    }
    errors = _positive_errors({"L_m": L_m, "k_W_mK": k_W_mK, "A_m2": A_m2})
    if heat_load_W is not None:
        errors.extend(_positive_errors({"heat_load_W": heat_load_W}))
    if errors:
        return _error_result(
            "conduction_resistance",
            inputs=inputs,
            formula=formula,
            message="; ".join(errors),
            engineering_note=note,
        )

    r_cond = float(L_m) / (float(k_W_mK) * float(A_m2))
    delta_t = None if heat_load_W is None else float(heat_load_W) * r_cond
    result = _base_result("conduction_resistance", inputs=inputs, formula=formula, engineering_note=note)
    result["calculation_steps"] = [
        f"R_cond = {L_m} / ({k_W_mK} * {A_m2}) = {_round_value(r_cond)} K/W",
    ]
    if heat_load_W is not None:
        result["calculation_steps"].append(f"delta_T = {heat_load_W} * {_round_value(r_cond)} = {_round_value(delta_t)} K")
    result["result"] = {
        "R_cond_K_per_W": _round_value(r_cond),
        "delta_T_K": _round_value(delta_t),
    }
    result["unit_check"]["messages"].append("m / (W/(m*K) * m^2) gives K/W.")
    if float(L_m) > 0.005:
        result["warnings"].append("Conduction layer thickness is large; confirm the unit is meters.")
    if float(A_m2) < 1e-6:
        result["warnings"].append("Area is very small; confirm mm^2 was converted to m^2 correctly.")
    if float(k_W_mK) < 0.1:
        result["warnings"].append("Thermal conductivity is low for a high-power chip thermal path.")
    result["warnings"].append(note)
    return result


@_validated_calculation
def plane_wall_conduction(
    *,
    L_m: float,
    k_W_mK: float,
    A_m2: float,
    delta_T_K: float,
    material_name: str | None = None,
) -> CalculationResult:
    """Calculate one-dimensional steady heat conduction through a plane wall."""

    formula = "Q_dot_W = k_W_mK * A_m2 * delta_T_K / L_m"
    note = (
        "This is a one-dimensional steady plane-wall conduction approximation. It assumes constant thermal "
        "conductivity, uniform area, no internal heat generation, and negligible contact/edge effects."
    )
    inputs = {
        "L_m": L_m,
        "k_W_mK": k_W_mK,
        "A_m2": A_m2,
        "delta_T_K": delta_T_K,
        "material_name": material_name,
    }
    errors = _positive_errors({"L_m": L_m, "k_W_mK": k_W_mK, "A_m2": A_m2, "delta_T_K": delta_T_K})
    if errors:
        return _error_result(
            "plane_wall_conduction",
            inputs=inputs,
            formula=formula,
            message="; ".join(errors),
            engineering_note=note,
        )

    r_cond = float(L_m) / (float(k_W_mK) * float(A_m2))
    heat_rate = float(k_W_mK) * float(A_m2) * float(delta_T_K) / float(L_m)
    heat_flux = heat_rate / float(A_m2)
    result = _base_result("plane_wall_conduction", inputs=inputs, formula=formula, engineering_note=note)
    result["calculation_steps"] = [
        f"delta_T = {delta_T_K} K",
        f"R_cond = {L_m} / ({k_W_mK} * {A_m2}) = {_round_value(r_cond)} K/W",
        f"Q_dot = {k_W_mK} * {A_m2} * {delta_T_K} / {L_m} = {_round_value(heat_rate)} W",
    ]
    result["result"] = {
        "heat_rate_W": _round_value(heat_rate),
        "heat_flux_W_m2": _round_value(heat_flux),
        "R_cond_K_per_W": _round_value(r_cond),
        "delta_T_K": _round_value(float(delta_T_K)),
    }
    result["unit_check"]["messages"].append("W/(m*K) * m^2 * K / m gives W.")
    if float(L_m) <= 0:
        result["warnings"].append("Plane-wall thickness must be positive.")
    if float(k_W_mK) < 0.1:
        result["warnings"].append("Thermal conductivity is low; confirm the material and units.")
    result["warnings"].append(note)
    # Check unrounded SI outputs. This is an algebraic consistency check, not
    # independent simulation evidence or mesh/convergence verification.
    validation = validate_physics(PhysicsValidationRequest(
        quantities=[
            {"name": "heat_rate", "value": heat_rate, "unit": "W", "positive": True},
            {"name": "heat_flux", "value": heat_flux, "unit": "W/m2", "positive": True},
            {"name": "resistance", "value": r_cond, "unit": "K/W", "positive": True},
        ],
        energy_balance={"heat_input_w": heat_rate, "heat_output_w": heat_flux * float(A_m2), "relative_tolerance": 1e-9},
    ))
    result["physics_validation"] = validation.model_dump()
    if not validation.passed:
        result.update(status="error", result={}, error="Deterministic physical consistency checks failed.")
        result["unit_check"] = {"status": "failed", "messages": [item.message for item in validation.issues]}
    return result


@_validated_calculation
def coolant_temperature_rise(
    *,
    Q_W: float,
    m_dot_kg_s: float,
    cp_J_kgK: float,
    T_in_C: float | None = None,
    fluid_name: str | None = None,
) -> CalculationResult:
    """Calculate coolant temperature rise from energy conservation."""

    formula = "delta_T_K = Q_W / (m_dot_kg_s * cp_J_kgK)"
    note = (
        "This energy-balance estimate assumes all heat is carried by the coolant. It omits heat losses, "
        "cold-plate efficiency, channel maldistribution, and sensor uncertainty."
    )
    inputs = {
        "Q_W": Q_W,
        "m_dot_kg_s": m_dot_kg_s,
        "cp_J_kgK": cp_J_kgK,
        "T_in_C": T_in_C,
        "fluid_name": fluid_name,
    }
    errors = _positive_errors({"Q_W": Q_W, "m_dot_kg_s": m_dot_kg_s, "cp_J_kgK": cp_J_kgK})
    if errors:
        return _error_result(
            "coolant_temperature_rise",
            inputs=inputs,
            formula=formula,
            message="; ".join(errors),
            engineering_note=note,
        )

    delta_t = float(Q_W) / (float(m_dot_kg_s) * float(cp_J_kgK))
    t_out = None if T_in_C is None else float(T_in_C) + delta_t
    result = _base_result("coolant_temperature_rise", inputs=inputs, formula=formula, engineering_note=note)
    result["calculation_steps"] = [
        f"delta_T = {Q_W} / ({m_dot_kg_s} * {cp_J_kgK}) = {_round_value(delta_t)} K",
    ]
    if T_in_C is not None:
        result["calculation_steps"].append(f"T_out = {T_in_C} + {_round_value(delta_t)} = {_round_value(t_out)} degC")
    result["result"] = {
        # Downstream curves and energy checks consume these machine values.
        # Round only the human-readable calculation_steps above.
        "delta_T_K": delta_t,
        "T_out_C": t_out,
    }
    result["unit_check"]["messages"].append("W / (kg/s * J/(kg*K)) gives K.")
    if delta_t > 15:
        result["warnings"].append("Coolant temperature rise is high; flow may be insufficient or heat load high.")
    if delta_t < 0.5:
        result["warnings"].append("Coolant temperature rise is very small; confirm flow rate and heat load.")
    if float(cp_J_kgK) < 1000 or float(cp_J_kgK) > 6000:
        result["warnings"].append("cp is outside the common liquid range; confirm coolant properties.")
    result["warnings"].append(note)
    return result


@_validated_calculation
def liquid_flow_rate_required(
    *,
    Q_W: float,
    delta_T_K: float,
    cp_J_kgK: float | None = None,
    rho_kg_m3: float | None = None,
    fluid_name: str | None = None,
) -> CalculationResult:
    """Estimate required mass and volume flow for an allowed coolant temperature rise."""

    formula = "m_dot = Q_W / (cp_J_kgK * delta_T_K); if rho is provided, V_dot = m_dot / rho_kg_m3"
    note = (
        "This ideal energy-balance flow estimate does not include cold-plate resistance, pressure drop, "
        "pump curve, local losses, flow distribution, contact resistance, or design safety margin."
    )
    assumptions: list[str] = []
    warnings: list[str] = []
    water_names = {"water", "cooling water", "水", "冷却水"}
    explicit_water = str(fluid_name or "").strip().lower() in water_names
    if cp_J_kgK is None:
        if explicit_water:
            cp_J_kgK = 4180.0
            assumptions.append("Default water cp_J_kgK = 4180 was used.")
            warnings.append("Coolant cp was not provided; water default was used. Glycol mixtures require table values.")
        else:
            cp_J_kgK = None
    if rho_kg_m3 is None and explicit_water:
        rho_kg_m3 = 1000.0
        assumptions.append("Default water rho_kg_m3 = 1000 was used.")
        warnings.append("Coolant density was not provided; water default was used. Glycol mixtures require table values.")

    inputs = {
        "Q_W": Q_W,
        "delta_T_K": delta_T_K,
        "cp_J_kgK": cp_J_kgK,
        "rho_kg_m3": rho_kg_m3,
        "fluid_name": fluid_name,
    }
    errors = _positive_errors({"Q_W": Q_W, "delta_T_K": delta_T_K, "cp_J_kgK": cp_J_kgK})
    if rho_kg_m3 is not None:
        errors.extend(_positive_errors({"rho_kg_m3": rho_kg_m3}))
    if errors:
        return _error_result(
            "liquid_flow_rate_required",
            inputs=inputs,
            formula=formula,
            message="; ".join(errors),
            engineering_note=note,
            assumptions=assumptions,
        )

    mass_flow = float(Q_W) / (float(cp_J_kgK) * float(delta_T_K))
    volume_flow = None if rho_kg_m3 is None else mass_flow / float(rho_kg_m3)
    volume_l_min = None if volume_flow is None else m3_s_to_l_min(volume_flow)
    result = _base_result(
        "liquid_flow_rate_required",
        inputs=inputs,
        formula=formula,
        engineering_note=note,
        assumptions=assumptions,
    )
    result["calculation_steps"] = [
        f"m_dot = {Q_W} / ({cp_J_kgK} * {delta_T_K}) = {_round_value(mass_flow)} kg/s",
    ]
    if rho_kg_m3 is not None:
        result["calculation_steps"].extend(
            [
                f"V_dot = {_round_value(mass_flow)} / {rho_kg_m3} = {_round_value(volume_flow)} m^3/s",
                f"L/min = {_round_value(volume_flow)} * 60000 = {_round_value(volume_l_min)} L/min",
            ]
        )
    result["result"] = {
        # These are machine-readable inputs to downstream pressure and energy
        # checks. Round only calculation_steps, never the physical state.
        "mass_flow_kg_s": mass_flow,
        "volume_flow_m3_s": volume_flow,
        "volume_flow_L_min": volume_l_min,
    }
    if rho_kg_m3 is None:
        result["unit_check"]["messages"].append("W / (J/(kg*K) * K) gives kg/s.")
        result["warnings"].append("Density was not provided, so volumetric flow was not calculated.")
    else:
        result["unit_check"]["messages"].append("W / (J/(kg*K) * K) gives kg/s; kg/s divided by kg/m^3 gives m^3/s.")
    result["warnings"].extend(warnings)
    if volume_l_min is not None and volume_l_min > 10:
        result["warnings"].append("Required flow is high; evaluate cold-plate pressure drop, pump curve, and piping.")
    if float(delta_T_K) < 2:
        result["warnings"].append("Allowed coolant temperature rise is small and will significantly increase flow.")
    if float(delta_T_K) > 15:
        result["warnings"].append("Allowed coolant temperature rise is large and may cause high outlet temperature.")
    result["warnings"].append(note)
    return result
