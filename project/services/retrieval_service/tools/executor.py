from __future__ import annotations

from typing import Any
import re

from ..properties.contracts import PROPERTY_LOOKUP_STATUSES
from ..properties.aliases import detect_fluid
from .contracts import (
    TOOL_STATUS_FAILED,
    TOOL_STATUS_MISSING_PARAMS,
    TOOL_STATUS_SKIPPED,
    TOOL_STATUS_SUCCESS,
    TOOL_STATUS_UNKNOWN_TOOL,
    ToolExecutionResult,
)
from .registry import DEFAULT_TOOL_REGISTRY, ToolRegistry
from .router import detect_calculation_tool
from .specs import REQUIRED_PARAMETERS, TOOL_FORMULAS, TOOL_FUNCTIONS, TOOL_NOTES
from .unit_parser import (
    has_water,
    normalize_text,
    parse_area_m2,
    parse_conductivity_w_mk,
    parse_cp_j_kgk,
    parse_delta_t_k,
    parse_density_kg_m3,
    parse_inlet_temperature_c,
    parse_limit_temperature_c,
    parse_mass_flow_kg_s,
    parse_plane_wall_temperature_difference_k,
    parse_power_w,
    parse_safety_margin_c,
    parse_thermal_resistance_k_per_w,
    parse_thickness_m,
    parse_volume_flow_m3_s,
    parse_volume_flow_l_min,
    parse_hydraulic_diameter_mm,
    parse_hydraulic_length_m,
    parse_dynamic_viscosity_pa_s,
    parse_minor_loss_coefficient,
    parse_friction_factor,
    parse_roughness_m,
    parse_temperature_c,
    parse_pressure_drop_kpa,
    parse_required_head_m,
)


PARAMETER_ALIASES: dict[str, dict[str, str]] = {
    "required_thermal_resistance": {
        "heat_load_W": "P_W",
        "power_W": "P_W",
        "T_limit_C": "T_max_C",
        "max_junction_temperature_C": "T_max_C",
        "reference_temperature_C": "T_in_C",
        "inlet_temperature_C": "T_in_C",
        "ambient_temperature_C": "T_in_C",
    },
    "junction_temperature_estimate": {
        "heat_load_W": "P_W",
        "power_W": "P_W",
        "reference_temperature_C": "T_in_C",
        "inlet_temperature_C": "T_in_C",
        "ambient_temperature_C": "T_in_C",
        "R_total": "R_total_K_per_W",
        "thermal_resistance_K_per_W": "R_total_K_per_W",
    },
    "conduction_resistance": {
        "thickness_m": "L_m",
        "thermal_conductivity_W_mK": "k_W_mK",
        "area_m2": "A_m2",
    },
    "plane_wall_conduction": {
        "thickness_m": "L_m",
        "thermal_conductivity_W_mK": "k_W_mK",
        "area_m2": "A_m2",
        "temperature_difference_K": "delta_T_K",
        "delta_T_C": "delta_T_K",
    },
    "coolant_temperature_rise": {
        "heat_load_W": "Q_W",
        "power_W": "Q_W",
        "mass_flow_kg_s": "m_dot_kg_s",
        "cp": "cp_J_kgK",
    },
    "liquid_flow_rate_required": {
        "heat_load_W": "Q_W",
        "power_W": "Q_W",
        "allowed_temperature_rise_K": "delta_T_K",
        "delta_T_C": "delta_T_K",
        "cp": "cp_J_kgK",
        "rho": "rho_kg_m3",
        "density_kg_m3": "rho_kg_m3",
    },
    "liquid_pressure_drop_estimate": {
        "flow_lpm": "flow_rate_lpm",
        "diameter_mm": "hydraulic_diameter_mm",
        "D_mm": "hydraulic_diameter_mm",
        "rho": "density_kg_m3",
        "mu": "dynamic_viscosity_pa_s",
        "K": "minor_loss_coefficient_k",
    },
}


def _normalize_input_aliases(tool_name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(inputs or {})
    for alias, canonical in PARAMETER_ALIASES.get(tool_name, {}).items():
        if canonical not in normalized and alias in normalized:
            normalized[canonical] = normalized[alias]
    return normalized


def _is_explicit_water(inputs: dict[str, Any]) -> bool:
    fluid = str(inputs.get("fluid_name") or inputs.get("coolant") or "").strip().lower()
    return fluid in {"water", "cooling water", "水", "冷却水"}


def _missing_for_spec(tool_name: str, inputs: dict[str, Any], required: list[str]) -> list[str]:
    if tool_name == "liquid_pressure_drop_estimate":
        missing: list[str] = []
        if inputs.get("flow_rate_lpm") is None and inputs.get("flow_rate_m3_s") is None:
            missing.append("flow_rate_lpm_or_flow_rate_m3_s")
        if inputs.get("hydraulic_diameter_mm") is None and inputs.get("pipe_diameter_mm") is None:
            missing.append("hydraulic_diameter_mm_or_pipe_diameter_mm")
        if inputs.get("length_m") is None:
            missing.append("length_m")
        explicit_water = _is_explicit_water(inputs)
        if inputs.get("density_kg_m3") is None and not explicit_water:
            missing.append("density_kg_m3")
        if inputs.get("dynamic_viscosity_pa_s") is None and not explicit_water:
            missing.append("dynamic_viscosity_pa_s")
        return missing
    missing = [name for name in required if inputs.get(name) is None]
    if tool_name == "liquid_flow_rate_required" and _is_explicit_water(inputs):
        missing = [name for name in missing if name not in {"cp_J_kgK", "rho_kg_m3"}]
    return missing


def _call_inputs(spec_required: list[str], spec_optional: list[str], inputs: dict[str, Any]) -> dict[str, Any]:
    allowed = set(spec_required) | set(spec_optional)
    return {key: value for key, value in inputs.items() if key in allowed}


def execute_tool(
    tool_name: str,
    inputs: dict[str, Any],
    registry: ToolRegistry | None = None,
) -> ToolExecutionResult:
    """Execute one ToolSpec-backed deterministic tool."""

    active_registry = registry or DEFAULT_TOOL_REGISTRY
    spec = active_registry.get(tool_name)
    raw_inputs = dict(inputs or {})
    if spec is None:
        return ToolExecutionResult(
            tool_name=tool_name,
            status=TOOL_STATUS_UNKNOWN_TOOL,
            inputs=raw_inputs,
            result=None,
            missing_parameters=[],
            assumptions=[],
            formula=None,
            steps=[],
            warnings=[],
            error=f"Unknown tool: {tool_name}",
        )

    normalized_inputs = _normalize_input_aliases(spec.name, raw_inputs)
    missing = _missing_for_spec(spec.name, normalized_inputs, spec.required_params)
    if missing:
        return ToolExecutionResult(
            tool_name=spec.name,
            status=TOOL_STATUS_MISSING_PARAMS,
            inputs=normalized_inputs,
            result=None,
            missing_parameters=missing,
            assumptions=[],
            formula=spec.formula,
            steps=[],
            warnings=list(spec.warnings),
            error="Missing required inputs: " + ", ".join(missing),
        )

    executor = active_registry.get_executor(spec.executor)
    if executor is None:
        return ToolExecutionResult(
            tool_name=spec.name,
            status=TOOL_STATUS_FAILED,
            inputs=normalized_inputs,
            result=None,
            missing_parameters=[],
            assumptions=[],
            formula=spec.formula,
            steps=[],
            warnings=list(spec.warnings),
            error=f"Executor is not mapped: {spec.executor}",
        )

    try:
        raw_result = executor(**_call_inputs(spec.required_params, spec.optional_params, normalized_inputs))
    except Exception as exc:
        return ToolExecutionResult(
            tool_name=spec.name,
            status=TOOL_STATUS_FAILED,
            inputs=normalized_inputs,
            result=None,
            missing_parameters=[],
            assumptions=[],
            formula=spec.formula,
            steps=[],
            warnings=list(spec.warnings),
            error=str(exc).strip() or exc.__class__.__name__,
        )

    if spec.domain == "coolant_properties":
        property_status = str(raw_result.get("status") or TOOL_STATUS_FAILED)
        if property_status not in PROPERTY_LOOKUP_STATUSES:
            property_status = TOOL_STATUS_FAILED
        warnings = list(raw_result.get("warnings") or [])
        for warning in spec.warnings:
            if warning not in warnings:
                warnings.append(warning)
        return ToolExecutionResult(
            tool_name=spec.name,
            status=property_status,
            inputs=dict(raw_result.get("inputs") or normalized_inputs),
            result=dict(raw_result),
            missing_parameters=list(raw_result.get("missing_fields") or raw_result.get("missing_parameters") or []),
            assumptions=[],
            formula=spec.formula,
            steps=[],
            warnings=warnings,
            error=raw_result.get("error"),
        )

    if spec.name == "liquid_network_flow_distribution":
        network_status = str(raw_result.get("network_status") or TOOL_STATUS_FAILED)
        status = {
            "success": TOOL_STATUS_SUCCESS,
            "missing_params": TOOL_STATUS_MISSING_PARAMS,
            "unsupported": TOOL_STATUS_FAILED,
            "failed": TOOL_STATUS_FAILED,
        }.get(network_status, TOOL_STATUS_FAILED)
        warnings = list(raw_result.get("warnings") or [])
        for warning in spec.warnings:
            if warning not in warnings:
                warnings.append(warning)
        return ToolExecutionResult(
            tool_name=spec.name,
            status=status,
            inputs=dict(raw_result.get("inputs") or normalized_inputs),
            result=dict(raw_result.get("result") or {}) if status == TOOL_STATUS_SUCCESS else None,
            missing_parameters=list(raw_result.get("missing_parameters") or []),
            assumptions=list(raw_result.get("assumptions") or []),
            formula=raw_result.get("formula") or spec.formula,
            steps=list(raw_result.get("calculation_steps") or []),
            warnings=warnings,
            error=raw_result.get("error") or ("unsupported network model" if network_status == "unsupported" else None),
        )

    if spec.name == "thermal_resistance_network_solve":
        network_status = str(raw_result.get("thermal_network_status") or TOOL_STATUS_FAILED)
        status = {
            "success": TOOL_STATUS_SUCCESS,
            "partial_result": TOOL_STATUS_MISSING_PARAMS,
            "missing_params": TOOL_STATUS_MISSING_PARAMS,
            "unsupported": TOOL_STATUS_FAILED,
            "failed": TOOL_STATUS_FAILED,
        }.get(network_status, TOOL_STATUS_FAILED)
        warnings = list(raw_result.get("warnings") or [])
        for warning in spec.warnings:
            if warning not in warnings:
                warnings.append(warning)
        return ToolExecutionResult(
            tool_name=spec.name,
            status=status,
            inputs=dict(raw_result.get("inputs") or normalized_inputs),
            result=(
                dict(raw_result.get("result") or {})
                if status == TOOL_STATUS_SUCCESS or network_status == "partial_result"
                else None
            ),
            missing_parameters=list(raw_result.get("missing_parameters") or []),
            assumptions=list(raw_result.get("assumptions") or []),
            formula=raw_result.get("formula") or spec.formula,
            steps=list(raw_result.get("calculation_steps") or []),
            warnings=warnings,
            error=raw_result.get("error") or ("unsupported thermal-network model" if network_status == "unsupported" else None),
        )

    status = TOOL_STATUS_SUCCESS if raw_result.get("status") == "ok" else TOOL_STATUS_FAILED
    return ToolExecutionResult(
        tool_name=spec.name,
        status=status,
        inputs=dict(raw_result.get("inputs") or normalized_inputs),
        result=dict(raw_result.get("result") or {}) if status == TOOL_STATUS_SUCCESS else None,
        missing_parameters=list(raw_result.get("missing_parameters") or []),
        assumptions=list(raw_result.get("assumptions") or []),
        formula=raw_result.get("formula") or spec.formula,
        steps=list(raw_result.get("calculation_steps") or []),
        warnings=list(raw_result.get("warnings") or []),
        error=raw_result.get("error"),
    )


def _missing(inputs: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [name for name in required if inputs.get(name) is None]


def parse_tool_inputs(query: str, tool_name: str | None = None) -> dict[str, Any]:
    """Parse natural-language parameters for a supported calculation tool.

    The parser is deterministic and conservative. Unknown or ambiguous values
    are left as None and reported as missing parameters.
    """

    text = normalize_text(query)
    selected = tool_name or detect_calculation_tool(text)
    fluid_name = "water" if has_water(text) else None
    parser_assumptions: list[str] = []
    parser_warnings: list[str] = []
    inputs: dict[str, Any] = {}

    if selected == "required_thermal_resistance":
        inputs = {
            "P_W": parse_power_w(text),
            "T_max_C": parse_limit_temperature_c(text),
            "T_in_C": parse_inlet_temperature_c(text),
            "safety_margin_C": parse_safety_margin_c(text) or 0.0,
        }

    elif selected == "junction_temperature_estimate":
        inputs = {
            "P_W": parse_power_w(text),
            "T_in_C": parse_inlet_temperature_c(text),
            "R_total_K_per_W": parse_thermal_resistance_k_per_w(text),
            "T_limit_C": parse_limit_temperature_c(text),
        }

    elif selected == "conduction_resistance":
        inputs = {
            "L_m": parse_thickness_m(text),
            "k_W_mK": parse_conductivity_w_mk(text),
            "A_m2": parse_area_m2(text),
            "material_name": None,
            "heat_load_W": None,
        }

    elif selected == "plane_wall_conduction":
        inputs = {
            "L_m": parse_thickness_m(text),
            "k_W_mK": parse_conductivity_w_mk(text),
            "A_m2": parse_area_m2(text),
            "delta_T_K": parse_plane_wall_temperature_difference_k(text),
            "material_name": None,
        }

    elif selected == "coolant_temperature_rise":
        cp = parse_cp_j_kgk(text)
        rho = parse_density_kg_m3(text)
        volume_flow = parse_volume_flow_m3_s(text)
        m_dot = parse_mass_flow_kg_s(text)
        if m_dot is None and volume_flow is not None:
            if rho is None and fluid_name == "water":
                rho = 1000.0
                parser_assumptions.append("Assumed water density rho_kg_m3 = 1000 to convert volume flow to mass flow.")
                parser_warnings.append("Water density default was used for volume-flow conversion.")
            if rho is not None:
                m_dot = float(volume_flow) * float(rho)
        if cp is None and fluid_name == "water":
            cp = 4180.0
            parser_assumptions.append("Assumed water cp_J_kgK = 4180.")
            parser_warnings.append("Water specific heat default was used; glycol mixtures require explicit properties.")
        inputs = {
            "Q_W": parse_power_w(text),
            "m_dot_kg_s": m_dot,
            "cp_J_kgK": cp,
            "T_in_C": parse_inlet_temperature_c(text),
            "fluid_name": fluid_name,
        }

    elif selected == "liquid_flow_rate_required":
        cp = parse_cp_j_kgk(text)
        rho = parse_density_kg_m3(text)
        inputs = {
            "Q_W": parse_power_w(text),
            "delta_T_K": parse_delta_t_k(text),
            "cp_J_kgK": cp,
            "rho_kg_m3": rho,
            "fluid_name": fluid_name,
        }

    elif selected == "liquid_pressure_drop_estimate":
        coolant = detect_fluid(text)
        inputs = {
            "flow_rate_lpm": parse_volume_flow_l_min(text),
            "flow_rate_m3_s": parse_volume_flow_m3_s(text),
            "hydraulic_diameter_mm": parse_hydraulic_diameter_mm(text),
            "pipe_diameter_mm": None,
            "length_m": parse_hydraulic_length_m(text),
            "density_kg_m3": parse_density_kg_m3(text),
            "dynamic_viscosity_pa_s": parse_dynamic_viscosity_pa_s(text),
            "minor_loss_coefficient_k": parse_minor_loss_coefficient(text),
            "friction_factor": parse_friction_factor(text),
            "roughness_m": parse_roughness_m(text),
            "temperature_c": parse_temperature_c(text),
            "coolant": coolant,
            "concentration_percent": None,
            "safety_factor": None,
            "parallel_channels": None,
            "notes": None,
        }
        fluid_name = coolant

    elif selected == "liquid_network_flow_distribution":
        lowered = text.lower()
        topology = "parallel" if ("并联" in text or "parallel" in lowered) else ("series" if ("串联" in text or "series" in lowered) else "unknown")
        chinese_counts = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}
        identical_phrase = r"(?:完全相同|结构相同|阻力特性(?:相同|一致)|等阻力|identical|same\s+(?:geometry|resistance))"
        count_match = re.search(
            rf"(?:(\d+)\s*个?|([两二三四五六七八])\s*(?:个|路)?)(?:{identical_phrase})?的?(?:并联|串联)(?:支路|冷板|元件|组件)",
            text,
            re.IGNORECASE,
        )
        branch_count = int(count_match.group(1)) if count_match and count_match.group(1) else (chinese_counts.get(count_match.group(2)) if count_match else None)
        total_flow_lpm = parse_volume_flow_l_min(text) if re.search(r"总流量|total\s+flow", text, re.IGNORECASE) else None
        identical = bool(re.search(identical_phrase, text, re.IGNORECASE))
        resistances: list[float] = []
        resistance_match = re.search(r"(?:阻力系数|resistance(?:\s+coefficients?)?)(?:分别)?(?:为|=|:)?\s*(.+?)(?=指数|\bn\s*=|总流量|total\s+flow|$)", text, re.IGNORECASE)
        if resistance_match:
            resistances = [float(value) for value in re.findall(r"\d+(?:\.\d+)?(?:e[+-]?\d+)?", resistance_match.group(1), re.IGNORECASE)]
        exponent_match = re.search(r"(?:指数|\bn)\s*(?:为|=|:)?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        exponent = float(exponent_match.group(1)) if exponent_match else None
        branches: list[dict[str, Any]] = []
        if topology == "parallel" and branch_count:
            for index in range(branch_count):
                branch = {"branch_id": f"branch_{index + 1}"}
                if identical:
                    branch["identical_group_id"] = "explicit_identical_group"
                if index < len(resistances):
                    branch["resistance_coefficient"] = resistances[index]
                    branch["resistance_exponent"] = exponent
                branches.append(branch)
        pressure_values: list[float] = []
        if topology == "series" and re.search(r"压降分别|pressure\s+drops?", text, re.IGNORECASE):
            for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(MPa|kPa|Pa)\b", text, re.IGNORECASE):
                scale = {"pa": 1.0, "kpa": 1000.0, "mpa": 1_000_000.0}[unit.lower()]
                pressure_values.append(float(value) * scale)
        components = [{"component_id": f"component_{i+1}", "pressure_drop_pa": value} for i, value in enumerate(pressure_values)]
        assumptions = ["identical_branches_explicit"] if identical else []
        network = {"network_id": "parsed_network", "topology": topology, "total_flow_rate_lpm": total_flow_lpm,
            "total_flow_rate_m3_s": None, "branches": branches, "components": components, "assumptions": assumptions, "warnings": []}
        inputs = {"network": network}

    elif selected == "thermal_resistance_network_solve":
        lowered = text.lower()
        topology = "parallel" if ("并联" in text or "parallel" in lowered) else "series"
        heat_load = parse_power_w(text)
        reference_match = re.search(
            r"(?:冷却液|环境|参考|入口|reference|ambient|coolant)\s*(?:温度)?\s*(?:为|=|:)?\s*(-?\d+(?:\.\d+)?)\s*(?:℃|°?C)",
            text,
            re.IGNORECASE,
        )
        allowable_match = re.search(
            r"(?:允许|最高|上限|allowable|max(?:imum)?)\s*(?:结温|junction\s*temperature|Tj)?\s*(?:为|=|:)?\s*(-?\d+(?:\.\d+)?)\s*(?:℃|°?C)",
            text,
            re.IGNORECASE,
        )
        reference_temperature = float(reference_match.group(1)) if reference_match else None
        allowable_temperature = float(allowable_match.group(1)) if allowable_match else None

        elements: list[dict[str, Any]] = []
        resistance_pattern = re.compile(
            r"(?:(封装热阻|TIM|冷板|热阻)\s*)?(\d+(?:\.\d+)?)\s*(?:K/W|K·W-1)",
            re.IGNORECASE,
        )
        label_counts: dict[str, int] = {}
        for index, match in enumerate(resistance_pattern.finditer(text)):
            label = str(match.group(1) or "thermal_resistance").strip()
            normalized_label = {"封装热阻": "package", "tim": "tim", "冷板": "cold_plate", "热阻": "resistance"}.get(label.lower(), label.lower())
            label_counts[normalized_label] = label_counts.get(normalized_label, 0) + 1
            suffix = f"_{label_counts[normalized_label]}" if label_counts[normalized_label] > 1 or normalized_label == "resistance" else ""
            elements.append(
                {
                    "element_id": f"{normalized_label}{suffix or (f'_{index + 1}' if normalized_label == 'thermal_resistance' else '')}",
                    "name": label,
                    "element_type": "explicit",
                    "resistance_k_per_w": float(match.group(2)),
                }
            )
        resistance_list_match = re.search(
            r"(?:串联热阻|并联热阻|thermal\s+resistances?)(.+?)K/W",
            text,
            re.IGNORECASE,
        )
        if resistance_list_match:
            listed_values = [
                float(value)
                for value in re.findall(r"\d+(?:\.\d+)?", resistance_list_match.group(1))
            ]
            if len(listed_values) > len(elements):
                elements = [
                    {
                        "element_id": f"resistance_{index + 1}",
                        "name": f"Thermal resistance {index + 1}",
                        "element_type": "explicit",
                        "resistance_k_per_w": value,
                    }
                    for index, value in enumerate(listed_values)
                ]

        if not elements and re.search(r"TIM|导热|conduction", text, re.IGNORECASE):
            thickness = parse_thickness_m(text)
            conductivity = parse_conductivity_w_mk(text)
            if conductivity is None:
                conductivity_match = re.search(
                    r"(?:导热率|thermal\s+conductivity)\s*(?:为|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:W/mK|W/\(m[·*]?K\))",
                    text,
                    re.IGNORECASE,
                )
                conductivity = float(conductivity_match.group(1)) if conductivity_match else None
            area = parse_area_m2(text)
            elements.append(
                {
                    "element_id": "tim" if re.search(r"TIM", text, re.IGNORECASE) else "conduction_layer",
                    "name": "TIM" if re.search(r"TIM", text, re.IGNORECASE) else "Conduction layer",
                    "element_type": "conduction",
                    "resistance_k_per_w": None,
                    "thickness_m": thickness,
                    "thermal_conductivity_w_mk": conductivity,
                    "area_m2": area,
                }
            )
        if not elements and re.search(r"对流|convection", text, re.IGNORECASE):
            h_match = re.search(
                r"(?:对流换热系数|换热系数|\bh\b)\s*(?:为|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:W/m2K|W/\(m[²2][·*]?K\))",
                text,
                re.IGNORECASE,
            )
            elements.append(
                {
                    "element_id": "convection_boundary",
                    "name": "Convection boundary",
                    "element_type": "convection",
                    "resistance_k_per_w": None,
                    "heat_transfer_coefficient_w_m2k": float(h_match.group(1)) if h_match else None,
                    "area_m2": parse_area_m2(text),
                }
            )
        missing_cold_plate = bool(
            re.search(
                r"(?:没有|缺少|缺失|未知|未提供)\s*(?:冷板|cold\s*plate)(?:热阻|\s+resistance)|"
                r"(?:冷板|cold\s*plate)(?:热阻|\s+resistance)\s*(?:没有|缺少|缺失|未知|未提供)",
                text,
                re.IGNORECASE,
            )
        )
        if missing_cold_plate and not any(row.get("element_id") == "cold_plate" for row in elements):
            elements.append(
                {
                    "element_id": "cold_plate",
                    "name": "冷板热阻",
                    "element_type": "explicit",
                    "resistance_k_per_w": None,
                    "missing_parameter_name": "cold_plate_resistance_k_per_w",
                }
            )
        network = {
            "network_id": "parsed_thermal_network",
            "topology": topology,
            "heat_load_w": heat_load,
            "reference_temperature_c": reference_temperature,
            "allowable_junction_temperature_c": allowable_temperature,
            "elements": elements,
            "nodes": [],
            "connections": [],
            "components": [],
            "assumptions": [],
            "warnings": [],
        }
        inputs = {"network": network}

    if selected is None:
        missing_parameters: list[str] = []
    else:
        required = REQUIRED_PARAMETERS[selected]
        missing_parameters = _missing(inputs, required)
        if selected == "liquid_flow_rate_required" and fluid_name == "water":
            missing_parameters = [name for name in missing_parameters if name not in {"cp_J_kgK", "rho_kg_m3"}]
        if (selected == "liquid_flow_rate_required" and fluid_name != "water"
                and inputs.get("rho_kg_m3") is None
                and re.search(r"体积流量|\bLPM\b|L\s*/\s*(?:min|s|h)|m(?:3|³)\s*/\s*(?:s|h)|升\s*(?:/|每)\s*(?:分钟|分|秒|小时)|升\s*(?:分钟|每分钟)|volume\s+flow", text, re.IGNORECASE)):
            # Density is optional for mass flow, but required for the explicitly
            # requested volumetric output. Never substitute water silently.
            if "rho_kg_m3" not in missing_parameters:
                missing_parameters.append("rho_kg_m3")
        if selected == "liquid_pressure_drop_estimate" and fluid_name == "water":
            missing_parameters = [
                name for name in missing_parameters if name not in {"density_kg_m3", "dynamic_viscosity_pa_s"}
            ]

    return {
        "tool_name": selected,
        "inputs": inputs,
        "missing_parameters": missing_parameters,
        "fluid_name": fluid_name,
        "normalized_query": text,
        "assumptions": parser_assumptions,
        "warnings": parser_warnings,
        "pump_requirements": {
            "pressure_drop_kpa": parse_pressure_drop_kpa(text),
            "required_head_m": parse_required_head_m(text),
            "flow_rate_lpm": parse_volume_flow_l_min(text),
            "coolant": detect_fluid(text),
            "temperature_c": parse_temperature_c(text),
        },
    }


def _missing_result(parse: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(parse.get("tool_name") or "unknown")
    missing = list(parse.get("missing_parameters") or [])
    return {
        "tool_name": tool_name,
        "status": "error",
        "inputs": dict(parse.get("inputs") or {}),
        "formula": TOOL_FORMULAS.get(tool_name, ""),
        "calculation_steps": [],
        "result": {},
        "unit_check": {
            "status": "failed",
            "messages": [f"Missing required input: {name}" for name in missing],
        },
        "warnings": [
            "The agent did not infer all required inputs from the query; provide explicit engineering parameters before using the estimate."
        ],
        "assumptions": list(parse.get("assumptions") or []),
        "engineering_note": TOOL_NOTES.get(tool_name, ""),
        "error": "Missing required inputs: " + ", ".join(missing),
        "missing_parameters": missing,
        "parameter_parse": parse,
    }


def run_detected_tool(query: str) -> dict[str, Any] | None:
    """Detect, parse, and execute a local thermal calculation tool."""

    parse = parse_tool_inputs(query)
    tool_name = parse.get("tool_name")
    if tool_name is None:
        return None
    if parse.get("missing_parameters"):
        return _missing_result(parse)
    func = TOOL_FUNCTIONS[str(tool_name)]
    result = func(**dict(parse.get("inputs") or {}))
    result.setdefault("missing_parameters", [])
    result["parameter_parse"] = parse
    for assumption in parse.get("assumptions") or []:
        if assumption not in result["assumptions"]:
            result["assumptions"].append(assumption)
    for warning in parse.get("warnings") or []:
        if warning not in result["warnings"]:
            result["warnings"].insert(0, warning)
    return result


def execute_detected_tool(
    query: str,
    task: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> ToolExecutionResult:
    """Detect a calculation tool from a query, parse inputs, then execute it."""

    active_registry = registry or DEFAULT_TOOL_REGISTRY
    tool_name = detect_calculation_tool(query, task=task, registry=active_registry)
    if tool_name is None:
        return ToolExecutionResult(
            tool_name=None,
            status=TOOL_STATUS_SKIPPED,
            inputs={},
            result=None,
            missing_parameters=[],
            assumptions=[],
            formula=None,
            steps=[],
            warnings=[],
            error=None,
        )
    parsed = parse_tool_inputs(query, tool_name)
    result = execute_tool(tool_name, dict(parsed.get("inputs") or {}), registry=active_registry)
    assumptions = list(result.assumptions)
    for assumption in parsed.get("assumptions") or []:
        if assumption not in assumptions:
            assumptions.append(assumption)
    warnings = list(result.warnings)
    for warning in parsed.get("warnings") or []:
        if warning not in warnings:
            warnings.insert(0, warning)
    return ToolExecutionResult(
        tool_name=result.tool_name,
        status=result.status,
        inputs=result.inputs,
        result=result.result,
        missing_parameters=result.missing_parameters,
        assumptions=assumptions,
        formula=result.formula,
        steps=result.steps,
        warnings=warnings,
        error=result.error,
    )


__all__ = [
    "execute_detected_tool",
    "execute_tool",
    "parse_tool_inputs",
    "run_detected_tool",
]
