from __future__ import annotations

import math
from typing import Any

from ..properties.aliases import normalize_fluid
from .hydraulic_contracts import HydraulicCalculationResult


GRAVITY_M_S2 = 9.80665
PRESSURE_DROP_FORMULA = (
    "A = pi*D^2/4; v = Q/A; Re = rho*v*D/mu; "
    "delta_p = (f*L/D + K)*rho*v^2/2; H = delta_p/(rho*g)"
)
PRESSURE_DROP_SOURCE = {
    "type": "engineering_formula",
    "name": "Darcy-Weisbach pressure drop estimate",
}


def _json_safe(value: Any) -> Any:
    """Keep rejected numeric inputs out of strict JSON responses and Run records."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _rounded(value: float, places: int = 6) -> float:
    rounded = round(value, places)
    return value if value != 0 and rounded == 0 else rounded


def _numeric_errors(inputs: dict[str, Any]) -> list[str]:
    errors = []
    positive = {"flow_rate_lpm", "flow_rate_m3_s", "hydraulic_diameter_mm", "pipe_diameter_mm",
                "length_m", "density_kg_m3", "dynamic_viscosity_pa_s", "friction_factor", "safety_factor"}
    for name, value in inputs.items():
        if name in {"notes", "coolant"} or value is None:
            continue
        try:
            number = float(value)
            if isinstance(value, bool) or not math.isfinite(number):
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            errors.append(f"{name} must be a finite number (boolean values are not accepted)")
            continue
        if name in positive and number <= 0:
            errors.append(f"{name} must be positive")
        if name in {"roughness_m", "minor_loss_coefficient_k"} and number < 0:
            errors.append(f"{name} must be non-negative")
        if name == "parallel_channels" and (number <= 0 or not number.is_integer()):
            errors.append("parallel_channels must be a positive integer")
        if name == "temperature_c" and number < -273.15:
            errors.append("temperature_c must be >= -273.15 degC")
        if name == "concentration_percent" and not 0 <= number <= 100:
            errors.append("concentration_percent must be between 0 and 100")
    if not errors:
        for left, right, conversion in (("flow_rate_lpm", "flow_rate_m3_s", 1 / 60000),
                                        ("hydraulic_diameter_mm", "pipe_diameter_mm", 1)):
            if inputs[left] is not None and inputs[right] is not None and not math.isclose(
                float(inputs[left]) * conversion, float(inputs[right]), rel_tol=1e-9, abs_tol=0.0
            ):
                errors.append(f"{left} and {right} specify conflicting values")
    return errors


def _result(
    status: str,
    *,
    inputs: dict[str, Any],
    warnings: list[str] | None = None,
    missing_parameters: list[str] | None = None,
    assumptions: list[str] | None = None,
    error: str | None = None,
    **values: Any,
) -> HydraulicCalculationResult:
    return HydraulicCalculationResult(
        status=status,
        inputs=_json_safe(inputs),
        formula=PRESSURE_DROP_FORMULA,
        steps=list(values.pop("steps", []) or []),
        warnings=list(warnings or []),
        missing_parameters=list(missing_parameters or []),
        assumptions=list(assumptions or []),
        source=dict(PRESSURE_DROP_SOURCE),
        error=error,
        **values,
    )


def calculate_liquid_pressure_drop(
    *,
    flow_rate_lpm: float | None = None,
    flow_rate_m3_s: float | None = None,
    hydraulic_diameter_mm: float | None = None,
    pipe_diameter_mm: float | None = None,
    length_m: float | None = None,
    density_kg_m3: float | None = None,
    dynamic_viscosity_pa_s: float | None = None,
    minor_loss_coefficient_k: float | None = None,
    friction_factor: float | None = None,
    roughness_m: float | None = None,
    temperature_c: float | None = None,
    coolant: str | None = None,
    concentration_percent: float | None = None,
    safety_factor: float | None = None,
    parallel_channels: int | None = None,
    notes: str | None = None,
) -> HydraulicCalculationResult:
    """Return a one-dimensional Darcy-Weisbach engineering estimate."""

    normalized_fluid = normalize_fluid(coolant)
    diameter_mm = hydraulic_diameter_mm if hydraulic_diameter_mm is not None else pipe_diameter_mm
    inputs: dict[str, Any] = {
        "flow_rate_lpm": flow_rate_lpm,
        "flow_rate_m3_s": flow_rate_m3_s,
        "hydraulic_diameter_mm": hydraulic_diameter_mm,
        "pipe_diameter_mm": pipe_diameter_mm,
        "length_m": length_m,
        "density_kg_m3": density_kg_m3,
        "dynamic_viscosity_pa_s": dynamic_viscosity_pa_s,
        "minor_loss_coefficient_k": minor_loss_coefficient_k,
        "friction_factor": friction_factor,
        "roughness_m": roughness_m,
        "temperature_c": temperature_c,
        "coolant": normalized_fluid or coolant,
        "concentration_percent": concentration_percent,
        "safety_factor": safety_factor,
        "parallel_channels": parallel_channels,
        "notes": notes,
    }
    errors = _numeric_errors(inputs)
    if errors:
        return _result("failed", inputs=inputs, error="; ".join(errors))
    missing: list[str] = []
    if flow_rate_lpm is None and flow_rate_m3_s is None:
        missing.append("flow_rate_lpm_or_flow_rate_m3_s")
    if diameter_mm is None:
        missing.append("hydraulic_diameter_mm_or_pipe_diameter_mm")
    if length_m is None:
        missing.append("length_m")

    warnings: list[str] = []
    assumptions: list[str] = []
    if normalized_fluid == "water":
        if density_kg_m3 is None:
            density_kg_m3 = 1000.0
            assumptions.append("default_water_density_kg_m3=1000")
        if dynamic_viscosity_pa_s is None:
            dynamic_viscosity_pa_s = 0.001
            assumptions.append("default_water_dynamic_viscosity_pa_s=0.001")
        if assumptions:
            warnings.append(
                "default_water_assumption: approximate density and dynamic viscosity for water near room temperature were used."
            )
    else:
        if density_kg_m3 is None:
            missing.append("density_kg_m3")
        if dynamic_viscosity_pa_s is None:
            missing.append("dynamic_viscosity_pa_s")

    inputs["density_kg_m3"] = density_kg_m3
    inputs["dynamic_viscosity_pa_s"] = dynamic_viscosity_pa_s
    if missing:
        status = "missing_data" if normalized_fluid in {"EGW", "PGW"} and any(
            item in {"density_kg_m3", "dynamic_viscosity_pa_s"} for item in missing
        ) else "missing_params"
        return _result(
            status,
            inputs=inputs,
            warnings=warnings,
            missing_parameters=list(dict.fromkeys(missing)),
            assumptions=assumptions,
            error="Missing required hydraulic inputs: " + ", ".join(dict.fromkeys(missing)),
        )

    try:
        total_flow_m3_s = float(flow_rate_m3_s) if flow_rate_m3_s is not None else float(flow_rate_lpm) / 60000.0
        diameter_m = float(diameter_mm) / 1000.0
        length = float(length_m)
        density = float(density_kg_m3)
        viscosity = float(dynamic_viscosity_pa_s)
        channel_count = 1 if parallel_channels is None else int(float(parallel_channels))
        loss_k = 0.0 if minor_loss_coefficient_k is None else float(minor_loss_coefficient_k)
        applied_safety_factor = 1.0 if safety_factor is None else float(safety_factor)
        if min(total_flow_m3_s, diameter_m, length, density, viscosity) <= 0:
            raise ValueError("flow, diameter, length, density, and viscosity must be positive")
        if channel_count <= 0 or loss_k < 0 or applied_safety_factor <= 0:
            raise ValueError("parallel_channels and safety_factor must be positive; K must be non-negative")

        channel_flow_m3_s = total_flow_m3_s / channel_count
        area_m2 = math.pi * diameter_m**2 / 4.0
        velocity_m_s = channel_flow_m3_s / area_m2
        reynolds = density * velocity_m_s * diameter_m / viscosity
        if reynolds < 2300.0:
            flow_regime = "laminar"
            calculated_friction = 64.0 / reynolds
        elif reynolds < 4000.0:
            flow_regime = "transitional"
            calculated_friction = 0.3164 / reynolds**0.25
            warnings.append("transitional_flow_friction_factor_is_uncertain")
        else:
            flow_regime = "turbulent"
            if roughness_m is not None:
                relative_roughness = float(roughness_m) / diameter_m
                calculated_friction = 1.0 / (
                    -1.8 * math.log10((relative_roughness / 3.7) ** 1.11 + 6.9 / reynolds)
                ) ** 2
            else:
                calculated_friction = 0.3164 / reynolds**0.25
                warnings.append("smooth_pipe_friction_factor_estimate_without_roughness")
        used_friction = float(friction_factor) if friction_factor is not None else calculated_friction
        if used_friction <= 0:
            raise ValueError("friction_factor must be positive")

        dynamic_pressure_pa = density * velocity_m_s**2 / 2.0
        major_loss_pa = used_friction * (length / diameter_m) * dynamic_pressure_pa
        minor_loss_pa = loss_k * dynamic_pressure_pa
        pressure_drop_pa = (major_loss_pa + minor_loss_pa) * applied_safety_factor
        required_head_m = pressure_drop_pa / (density * GRAVITY_M_S2)
        positive_outputs = (total_flow_m3_s, total_flow_m3_s * 60000.0, channel_flow_m3_s,
                            area_m2, velocity_m_s, reynolds, used_friction, pressure_drop_pa,
                            pressure_drop_pa / 1000.0, required_head_m, major_loss_pa * applied_safety_factor)
        if not all(math.isfinite(value) and value > 0 for value in positive_outputs):
            raise ValueError("Numerical range exceeded; no finite positive hydraulic estimate was produced")
        if not math.isfinite(minor_loss_pa * applied_safety_factor):
            raise ValueError("Numerical range exceeded in minor pressure losses")
        if applied_safety_factor != 1.0:
            assumptions.append(f"pressure_drop_safety_factor={applied_safety_factor}")
        if channel_count > 1:
            assumptions.append(f"equal_flow_split_across_{channel_count}_parallel_channels")

        inputs.update(
            {
                "flow_rate_m3_s": total_flow_m3_s,
                "flow_rate_lpm": total_flow_m3_s * 60000.0,
                "hydraulic_diameter_m": diameter_m,
                "parallel_channels": channel_count,
                "safety_factor": applied_safety_factor,
            }
        )
        return _result(
            "success",
            inputs=inputs,
            warnings=warnings,
            assumptions=assumptions,
            pressure_drop_pa=_rounded(pressure_drop_pa),
            pressure_drop_kpa=_rounded(pressure_drop_pa / 1000.0),
            required_head_m=_rounded(required_head_m),
            flow_rate_m3_s=total_flow_m3_s,
            flow_rate_lpm=total_flow_m3_s * 60000.0,
            velocity_m_s=_rounded(velocity_m_s),
            reynolds_number=_rounded(reynolds),
            friction_factor=_rounded(used_friction, 8),
            flow_regime=flow_regime,
            major_loss_pa=_rounded(major_loss_pa * applied_safety_factor),
            minor_loss_pa=_rounded(minor_loss_pa * applied_safety_factor),
            steps=[
                "Convert flow rate and hydraulic diameter to SI units.",
                "Compute flow area, velocity, and Reynolds number.",
                "Determine or apply the Darcy friction factor.",
                "Compute major and minor pressure losses.",
                "Convert total pressure drop to required liquid head.",
            ],
        )
    except (TypeError, ValueError, ArithmeticError) as exc:
        return _result("failed", inputs=inputs, warnings=warnings, assumptions=assumptions, error=str(exc))


def liquid_pressure_drop_estimate(**kwargs: Any) -> dict[str, Any]:
    """ToolSpec adapter using the legacy deterministic calculation shape."""

    calculation = calculate_liquid_pressure_drop(**kwargs)
    payload = calculation.to_dict()
    result_fields = {
        key: payload.get(key)
        for key in (
            "pressure_drop_pa",
            "pressure_drop_kpa",
            "required_head_m",
            "flow_rate_m3_s",
            "flow_rate_lpm",
            "velocity_m_s",
            "reynolds_number",
            "friction_factor",
            "flow_regime",
            "major_loss_pa",
            "minor_loss_pa",
            "source",
        )
    }
    return {
        "tool_name": "liquid_pressure_drop_estimate",
        "status": "ok" if calculation.status == "success" else "error",
        "hydraulic_status": calculation.status,
        "inputs": calculation.inputs,
        "formula": calculation.formula,
        "calculation_steps": calculation.steps,
        "result": result_fields if calculation.status == "success" else {},
        "unit_check": {
            "status": "passed" if calculation.status == "success" else "failed",
            "messages": ["SI conversion applied for flow rate, diameter, pressure, and head."],
        },
        "warnings": calculation.warnings,
        "assumptions": calculation.assumptions,
        "engineering_note": "Engineering estimate only; not an experimental or CFD result.",
        "error": calculation.error,
        "missing_parameters": calculation.missing_parameters,
        "source": calculation.source,
    }


__all__ = [
    "GRAVITY_M_S2",
    "PRESSURE_DROP_FORMULA",
    "PRESSURE_DROP_SOURCE",
    "calculate_liquid_pressure_drop",
    "liquid_pressure_drop_estimate",
]
