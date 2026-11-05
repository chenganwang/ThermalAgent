from __future__ import annotations

from collections import Counter
from typing import Iterable

from .contracts import SimulationToolSpec


MATLAB_FUNCTION_EVAL_SPEC = SimulationToolSpec(
    tool_name="matlab_function_eval",
    display_name="MATLAB function evaluation",
    description=(
        "Execute a MATLAB-style function contract through the Simulation Service. "
        "Phase 1 defaults to Mock Adapter when MATLAB Engine is unavailable."
    ),
    software="matlab",
    default_adapter="mock",
    supported_adapters=["mock", "matlab"],
    required_inputs=["function_name", "parameters"],
    optional_inputs=["expected_outputs", "units"],
    input_schema={
        "type": "object",
        "required": ["function_name", "parameters"],
        "properties": {
            "function_name": {"type": "string"},
            "parameters": {"type": "object"},
            "expected_outputs": {"type": "array", "items": {"type": "string"}},
            "units": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "values": {"type": "object"},
            "tables": {"type": "array"},
            "series": {"type": "array"},
        },
    },
    warnings=[
        "Phase 1 does not require real MATLAB Engine.",
        "Mock output must be clearly marked and must not be presented as real solver output.",
    ],
    category="matlab",
    tags=["matlab", "mock-safe"],
    mock_supported=True,
    real_backend_supported=False,
)


LIQUID_COOLING_TEMP_RISE_MOCK_SPEC = SimulationToolSpec(
    tool_name="liquid_cooling_temp_rise_mock",
    display_name="Mock liquid-cooling temperature rise",
    description="Deterministic mock energy-balance temperature-rise result for Simulation Module contract tests.",
    software="mock",
    default_adapter="mock",
    supported_adapters=["mock"],
    required_inputs=["heat_load_w", "mass_flow_kg_s", "cp_j_kgk"],
    optional_inputs=["inlet_temperature_c"],
    input_schema={"type": "object", "required": ["heat_load_w", "mass_flow_kg_s", "cp_j_kgk"]},
    output_schema={"type": "object", "properties": {"coolant_temperature_rise_k": {"type": "number"}}},
    warnings=["Mock output is not real physical simulation."],
    category="mock",
    tags=["mock", "liquid-cooling"],
    mock_supported=True,
    real_backend_supported=False,
)


THERMAL_NETWORK_SOLVE_MOCK_SPEC = SimulationToolSpec(
    tool_name="thermal_network_solve_mock",
    display_name="Mock thermal-network solve",
    description="Deterministic mock one-dimensional thermal-network result for Simulation Module contract tests.",
    software="mock",
    default_adapter="mock",
    supported_adapters=["mock"],
    required_inputs=["heat_load_w", "resistances_k_per_w", "reference_temperature_c"],
    optional_inputs=[],
    input_schema={"type": "object", "required": ["heat_load_w", "resistances_k_per_w", "reference_temperature_c"]},
    output_schema={"type": "object", "properties": {"total_resistance_k_per_w": {"type": "number"}}},
    warnings=["Mock output is not CFD or real solver output."],
    category="mock",
    tags=["mock", "thermal-network"],
    mock_supported=True,
    real_backend_supported=False,
)


class SimulationRegistry:
    """Read-only registry for simulation tool metadata."""

    def __init__(self, specs: Iterable[SimulationToolSpec] | None = None) -> None:
        self._items = list(specs or [])
        self._specs = {spec.tool_name: spec for spec in self._items if spec.tool_name}

    def get(self, tool_name: str) -> SimulationToolSpec | None:
        return self._specs.get(tool_name)

    def require(self, tool_name: str) -> SimulationToolSpec:
        spec = self.get(tool_name)
        if spec is None:
            raise KeyError(f"Unknown simulation tool: {tool_name}")
        return spec

    def list(self) -> list[SimulationToolSpec]:
        return list(self._items)

    def names(self) -> list[str]:
        return [spec.tool_name for spec in self._items]

    def find_by_adapter(self, adapter_name: str) -> list[SimulationToolSpec]:
        return [spec for spec in self._items if adapter_name in spec.supported_adapters]

    def validate(self) -> list[str]:
        errors: list[str] = []
        names = [spec.tool_name for spec in self._items]
        for name, count in Counter(names).items():
            if name and count > 1:
                errors.append(f"duplicate simulation tool name: {name}")
        for index, spec in enumerate(self._items):
            label = spec.tool_name or f"<index {index}>"
            if not spec.tool_name:
                errors.append(f"{label}: tool_name must not be empty")
            if not spec.default_adapter:
                errors.append(f"{label}: default_adapter must not be empty")
            if spec.default_adapter not in spec.supported_adapters:
                errors.append(f"{label}: default_adapter must be supported")
            if not spec.required_inputs:
                errors.append(f"{label}: required_inputs must not be empty")
            if spec.supports_mock and "mock" not in spec.supported_adapters:
                errors.append(f"{label}: supports_mock requires mock adapter")
        return errors


DEFAULT_SIMULATION_REGISTRY = SimulationRegistry(
    [
        MATLAB_FUNCTION_EVAL_SPEC,
        LIQUID_COOLING_TEMP_RISE_MOCK_SPEC,
        THERMAL_NETWORK_SOLVE_MOCK_SPEC,
    ]
)


__all__ = [
    "DEFAULT_SIMULATION_REGISTRY",
    "LIQUID_COOLING_TEMP_RISE_MOCK_SPEC",
    "MATLAB_FUNCTION_EVAL_SPEC",
    "SimulationRegistry",
    "THERMAL_NETWORK_SOLVE_MOCK_SPEC",
]
