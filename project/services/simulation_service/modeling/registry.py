from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    value_type: str
    canonical_unit: str
    accepted_units: tuple[str, ...]
    required: bool = True
    default: float | int | None = None
    minimum: float | None = None
    maximum: float | None = None
    critical: bool = True
    compiler_parameter: str | None = None
    compiler_unit_parameter: str | None = None
    compiler_unit: str | None = None


@dataclass(frozen=True)
class PortSpec:
    name: str
    domain: str
    required: bool = True
    multiple: bool = False
    compiler_handle_family: str | None = None
    compiler_handle_index: int = 0


@dataclass(frozen=True)
class ComponentSpec:
    component_type: str
    display_name: str
    domain: str
    parameters: tuple[ParameterSpec, ...]
    ports: tuple[PortSpec, ...]
    compiler_mapping: dict[str, Any]
    supported_matlab_versions: tuple[str, ...] = ("R2025a",)
    availability: str = "reviewed"
    compiler_available: bool = False
    capability_requirements: tuple[str, ...] = ()

    def parameter(self, name: str) -> ParameterSpec | None:
        return next((item for item in self.parameters if item.name == name), None)

    def port(self, name: str) -> PortSpec | None:
        return next((item for item in self.ports if item.name == name), None)

    def public_summary(self) -> dict[str, Any]:
        return {
            "component_type": self.component_type,
            "display_name": self.display_name,
            "domain": self.domain,
            "parameters": [
                {
                    key: value for key, value in asdict(item).items()
                    if key not in {"compiler_parameter", "compiler_unit_parameter", "compiler_unit"}
                }
                for item in self.parameters
            ],
            "ports": [
                {
                    key: value for key, value in asdict(item).items()
                    if key not in {"compiler_handle_family", "compiler_handle_index"}
                }
                for item in self.ports
            ],
            "supported_matlab_versions": list(self.supported_matlab_versions),
            "availability": self.availability,
            "compiler_available": self.compiler_available,
            "capability_requirements": list(self.capability_requirements),
        }


class ComponentRegistry:
    registry_version = "thermal-components-r2025a-v3"

    def __init__(self, components: tuple[ComponentSpec, ...]) -> None:
        self._items: dict[str, ComponentSpec] = {}
        for item in components:
            if item.component_type in self._items:
                raise ValueError(f"duplicate component mapping: {item.component_type}")
            if any(not parameter.canonical_unit for parameter in item.parameters):
                raise ValueError(f"component parameter lacks canonical unit: {item.component_type}")
            if any(not port.domain for port in item.ports):
                raise ValueError(f"component port lacks domain: {item.component_type}")
            if item.compiler_available:
                if not str(item.compiler_mapping.get("block_path") or "").strip():
                    raise ValueError(f"compiler-ready component lacks reviewed block path: {item.component_type}")
                if any(not port.compiler_handle_family for port in item.ports):
                    raise ValueError(f"compiler-ready component lacks reviewed port locator: {item.component_type}")
            self._items[item.component_type] = item

    @classmethod
    def default(cls) -> "ComponentRegistry":
        requirements = ("simulink", "simscape", "thermal")
        thermal_ports = (
            PortSpec("A", "thermal", compiler_handle_family="LConn"),
            PortSpec("B", "thermal", compiler_handle_family="RConn"),
        )
        return cls((
            ComponentSpec(
                "temperature_source", "Temperature Source", "thermal",
                (ParameterSpec(
                    "temperature_k", "number", "K", ("K", "degC", "°C"),
                    minimum=0.0, maximum=5000.0, compiler_parameter="temperature",
                    compiler_unit_parameter="temperature_unit", compiler_unit="K",
                ),),
                (PortSpec("A", "thermal", compiler_handle_family="LConn"),),
                {
                    "library_id": "fl_lib", "block_key": "temperature_source",
                    "block_path": "fl_lib/Thermal/Thermal Sources/Temperature Source",
                },
                compiler_available=True,
                capability_requirements=requirements,
            ),
            ComponentSpec(
                "thermal_resistance", "Thermal Resistance", "thermal",
                (ParameterSpec(
                    "resistance_k_w", "number", "K/W", ("K/W",), minimum=0.0,
                    compiler_parameter="resistance", compiler_unit_parameter="resistance_unit", compiler_unit="K/W",
                ),),
                thermal_ports,
                {
                    "library_id": "fl_lib", "block_key": "thermal_resistance",
                    "block_path": "fl_lib/Thermal/Thermal Elements/Thermal Resistance",
                },
                compiler_available=True,
                capability_requirements=requirements,
            ),
            ComponentSpec(
                "conductive_layer", "Conductive Layer", "thermal",
                (
                    ParameterSpec("thickness_m", "number", "m", ("m",), minimum=0.0),
                    ParameterSpec(
                        "conductivity_w_mk", "number", "W/(m*K)",
                        ("W/(m*K)", "W/(m·K)"), minimum=0.0,
                    ),
                    ParameterSpec("area_m2", "number", "m^2", ("m^2", "m2", "cm^2"), minimum=0.0),
                ),
                thermal_ports,
                {
                    "library_id": "fl_lib", "block_key": "thermal_resistance",
                    "block_path": "fl_lib/Thermal/Thermal Elements/Thermal Resistance",
                    "lowering": "layer_to_resistance",
                },
                compiler_available=True,
                capability_requirements=requirements,
            ),
            ComponentSpec(
                "thermal_mass", "Thermal Mass", "thermal",
                (
                    ParameterSpec(
                        "mass_kg", "number", "kg", ("kg", "g"), minimum=0.0,
                        compiler_parameter="mass", compiler_unit_parameter="mass_unit", compiler_unit="kg",
                    ),
                    ParameterSpec(
                        "specific_heat_j_kgk", "number", "J/(kg*K)", ("J/(kg*K)", "J/(K*kg)"),
                        minimum=0.0, compiler_parameter="sp_heat", compiler_unit_parameter="sp_heat_unit",
                        compiler_unit="J/(K*kg)",
                    ),
                ),
                (PortSpec("M", "thermal", compiler_handle_family="LConn"),),
                {
                    "library_id": "fl_lib", "block_key": "thermal_mass",
                    "block_path": "fl_lib/Thermal/Thermal Elements/Thermal Mass",
                },
                compiler_available=True,
                capability_requirements=requirements,
            ),
            ComponentSpec(
                "convective_heat_transfer", "Convective Heat Transfer", "thermal",
                (
                    ParameterSpec(
                        "area_m2", "number", "m^2", ("m^2", "m2", "cm^2"), minimum=0.0,
                        compiler_parameter="area", compiler_unit_parameter="area_unit", compiler_unit="m^2",
                    ),
                    ParameterSpec(
                        "heat_transfer_coefficient_w_m2k", "number", "W/(m^2*K)",
                        ("W/(m^2*K)", "W/(m2*K)"), minimum=0.0,
                        compiler_parameter="heat_tr_coeff", compiler_unit_parameter="heat_tr_coeff_unit",
                        compiler_unit="W/(K*m^2)",
                    ),
                ),
                thermal_ports,
                {
                    "library_id": "fl_lib", "block_key": "convective_heat_transfer",
                    "block_path": "fl_lib/Thermal/Thermal Elements/Convective Heat\nTransfer",
                },
                compiler_available=True,
                capability_requirements=requirements,
            ),
            ComponentSpec(
                "thermal_reference", "Thermal Reference", "thermal", (),
                (PortSpec("H", "thermal", multiple=True, compiler_handle_family="LConn"),),
                {
                    "library_id": "fl_lib", "block_key": "thermal_reference",
                    "block_path": "fl_lib/Thermal/Thermal Elements/Thermal Reference",
                },
                compiler_available=True,
                capability_requirements=requirements,
            ),
            ComponentSpec(
                "solver_configuration", "Solver Configuration", "thermal", (),
                (PortSpec("network", "any_conserving", compiler_handle_family="RConn"),),
                {
                    "library_id": "nesl_utility", "block_key": "solver_configuration",
                    "block_path": "nesl_utility/Solver\nConfiguration",
                },
                compiler_available=True,
                capability_requirements=requirements,
            ),
        ))

    def get(self, component_type: str) -> ComponentSpec | None:
        return self._items.get(str(component_type))

    def require(self, component_type: str) -> ComponentSpec:
        item = self.get(component_type)
        if item is None:
            raise KeyError(component_type)
        return item

    def list(self, *, domain: str | None = None) -> list[ComponentSpec]:
        return [item for item in self._items.values() if domain is None or item.domain == domain]

    def public_summary(self, *, domain: str | None = None) -> list[dict[str, Any]]:
        return [
            item.public_summary()
            for item in self.list(domain=domain)
            if item.availability != "CAPABILITY_NOT_AVAILABLE"
        ]


__all__ = ["ComponentRegistry", "ComponentSpec", "ParameterSpec", "PortSpec"]
