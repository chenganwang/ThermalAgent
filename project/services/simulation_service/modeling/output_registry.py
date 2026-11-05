from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InstrumentationPort:
    logical_name: str
    handle_family: str
    handle_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "handle_family": self.handle_family,
            "handle_index": self.handle_index,
        }


@dataclass(frozen=True)
class OutputSpec:
    output_type: str
    quantity: str
    canonical_unit: str
    allowed_source_component_types: tuple[str, ...]
    instrumentation_mode: str
    source_port_by_component_type: dict[str, str]
    sensor_block_key: str
    sensor_library_id: str
    sensor_block_path: str
    sensor_a_port: InstrumentationPort
    sensor_b_port: InstrumentationPort
    sensor_signal_port: InstrumentationPort
    converter_block_key: str
    converter_library_id: str
    converter_block_path: str
    converter_input_port: InstrumentationPort
    converter_output_port: InstrumentationPort
    logger_block_key: str
    logger_library_id: str
    logger_block_path: str
    logger_input_port: InstrumentationPort
    max_samples: int = 512

    def public_summary(self) -> dict[str, Any]:
        return {
            "type": self.output_type,
            "quantity": self.quantity,
            "canonical_unit": self.canonical_unit,
            "allowed_source_component_types": list(self.allowed_source_component_types),
            "instrumentation_available": self.instrumentation_mode != "capability_gap",
            "max_samples": self.max_samples,
        }


class OutputRegistry:
    """Private reviewed R2025a output and instrumentation mappings."""

    registry_version = "thermal-outputs-r2025a-v1"

    def __init__(self, outputs: tuple[OutputSpec, ...]) -> None:
        self._items: dict[str, OutputSpec] = {}
        for item in outputs:
            if item.output_type in self._items:
                raise ValueError(f"duplicate output mapping: {item.output_type}")
            if not item.canonical_unit or not item.allowed_source_component_types:
                raise ValueError(f"incomplete output mapping: {item.output_type}")
            self._items[item.output_type] = item

    @classmethod
    def default(cls) -> "OutputRegistry":
        physical_a = InstrumentationPort("A", "LConn", 0)
        # R2025a fixed-port audit: physical-signal output is RConn[0];
        # conserving port B is RConn[1] for both reviewed thermal sensors.
        physical_signal = InstrumentationPort("signal", "RConn", 0)
        physical_b = InstrumentationPort("B", "RConn", 1)
        converter_input = InstrumentationPort("physical_signal", "LConn", 0)
        converter_output = InstrumentationPort("simulink_signal", "Outport", 0)
        logger_input = InstrumentationPort("input", "Inport", 0)
        shared = {
            "converter_block_key": "ps_simulink_converter",
            "converter_library_id": "nesl_utility",
            "converter_block_path": "nesl_utility/PS-Simulink\nConverter",
            "converter_input_port": converter_input,
            "converter_output_port": converter_output,
            "logger_block_key": "to_workspace",
            "logger_library_id": "simulink",
            "logger_block_path": "simulink/Sinks/To Workspace",
            "logger_input_port": logger_input,
        }
        return cls((
            OutputSpec(
                output_type="temperature",
                quantity="temperature",
                canonical_unit="K",
                allowed_source_component_types=(
                    "temperature_source", "thermal_mass", "thermal_resistance",
                    "conductive_layer", "convective_heat_transfer",
                ),
                instrumentation_mode="temperature_to_reference",
                source_port_by_component_type={
                    "temperature_source": "A", "thermal_mass": "M",
                    "thermal_resistance": "B", "conductive_layer": "B",
                    "convective_heat_transfer": "B",
                },
                sensor_block_key="temperature_sensor",
                sensor_library_id="fl_lib",
                sensor_block_path="fl_lib/Thermal/Thermal Sensors/Temperature Sensor",
                sensor_a_port=physical_a,
                sensor_b_port=physical_b,
                sensor_signal_port=physical_signal,
                **shared,
            ),
            OutputSpec(
                output_type="heat_flow",
                quantity="heat_flow_rate",
                canonical_unit="W",
                allowed_source_component_types=(
                    "thermal_resistance", "conductive_layer", "convective_heat_transfer",
                ),
                instrumentation_mode="series_after_source",
                source_port_by_component_type={
                    "thermal_resistance": "B",
                    "conductive_layer": "B",
                    "convective_heat_transfer": "B",
                },
                sensor_block_key="heat_flow_sensor",
                sensor_library_id="fl_lib",
                sensor_block_path="fl_lib/Thermal/Thermal Sensors/Heat Flow Rate\nSensor",
                sensor_a_port=physical_a,
                sensor_b_port=physical_b,
                sensor_signal_port=physical_signal,
                **shared,
            ),
        ))

    def get(self, output_type: str) -> OutputSpec | None:
        return self._items.get(str(output_type))

    def require(self, output_type: str) -> OutputSpec:
        item = self.get(output_type)
        if item is None:
            raise KeyError(output_type)
        return item

    def public_summary(self) -> list[dict[str, Any]]:
        return [item.public_summary() for item in self._items.values()]


__all__ = ["InstrumentationPort", "OutputRegistry", "OutputSpec"]
