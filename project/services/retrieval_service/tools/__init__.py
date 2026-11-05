"""Local deterministic tools used by the retrieval agent."""

from .contracts import ToolExecutionResult, ToolSpec
from .executor import execute_detected_tool, execute_tool
from .registry import DEFAULT_TOOL_REGISTRY, ToolRegistry
from .hydraulic_calculators import calculate_liquid_pressure_drop, liquid_pressure_drop_estimate
from .hydraulic_contracts import HydraulicCalculationResult, PumpSelectionPreparationResult
from .hydraulic_network_contracts import FlowDistributionResult, HydraulicBranch, HydraulicNetwork
from .hydraulic_network_calculators import calculate_network_flow_distribution, liquid_network_flow_distribution
from .flow_distribution_preparer import prepare_flow_distribution
from .thermal_network_contracts import (
    ThermalNetwork,
    ThermalNetworkNode,
    ThermalNetworkSolveResult,
    ThermalResistanceElement,
    ThermalSensitivityPlan,
)
from .thermal_network_calculators import solve_thermal_resistance_network, thermal_resistance_network_solve
from .thermal_path_builder import build_thermal_path_graph
from .thermal_bottleneck_analyzer import analyze_thermal_bottlenecks
from .thermal_sensitivity_preparer import prepare_thermal_sensitivity
from .pump_selection_preparer import prepare_pump_selection
from .thermal_calculators import (
    cm2_to_m2,
    conduction_resistance,
    coolant_temperature_rise,
    junction_temperature_estimate,
    kg_s_to_l_min_given_density,
    l_min_to_m3_s,
    liquid_flow_rate_required,
    m3_s_to_l_min,
    mm2_to_m2,
    mm_to_m,
    required_thermal_resistance,
)
from .tool_registry import (
    detect_calculation_tool,
    detect_property_lookup_tool,
    format_property_lookup_answer,
    format_tool_answer,
    parse_tool_inputs,
    run_detected_tool,
    run_property_lookup_tool,
)

__all__ = [
    "DEFAULT_TOOL_REGISTRY",
    "ToolExecutionResult",
    "ToolRegistry",
    "ToolSpec",
    "HydraulicCalculationResult",
    "HydraulicBranch",
    "HydraulicNetwork",
    "FlowDistributionResult",
    "ThermalNetwork",
    "ThermalNetworkNode",
    "ThermalNetworkSolveResult",
    "ThermalResistanceElement",
    "ThermalSensitivityPlan",
    "PumpSelectionPreparationResult",
    "calculate_liquid_pressure_drop",
    "calculate_network_flow_distribution",
    "solve_thermal_resistance_network",
    "thermal_resistance_network_solve",
    "build_thermal_path_graph",
    "analyze_thermal_bottlenecks",
    "prepare_thermal_sensitivity",
    "cm2_to_m2",
    "conduction_resistance",
    "coolant_temperature_rise",
    "detect_calculation_tool",
    "detect_property_lookup_tool",
    "execute_detected_tool",
    "execute_tool",
    "format_tool_answer",
    "format_property_lookup_answer",
    "junction_temperature_estimate",
    "kg_s_to_l_min_given_density",
    "l_min_to_m3_s",
    "liquid_flow_rate_required",
    "liquid_pressure_drop_estimate",
    "liquid_network_flow_distribution",
    "m3_s_to_l_min",
    "mm2_to_m2",
    "mm_to_m",
    "required_thermal_resistance",
    "parse_tool_inputs",
    "prepare_pump_selection",
    "prepare_flow_distribution",
    "run_detected_tool",
    "run_property_lookup_tool",
]
