from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


_PRODUCT_FEATURES = {
    "simulink": ("simulink", "dir", "Simulink", "Simulink"),
    "simscape": ("simscape", "dir", "Simscape", "Simscape"),
    "simscape_fluids": ("SimscapeFluids_lib", "file", "Simscape Fluids", "SimHydraulics"),
}

_REVIEWED_BLOCK_QUERIES = {
    "thermal_mass": ("fl_lib", "Thermal Mass"),
    "thermal_resistance": ("fl_lib", "Thermal Resistance"),
    "convective_heat_transfer": ("fl_lib", "Convective Heat Transfer"),
    "controlled_heat_flow_source": ("fl_lib", "Controlled Heat Flow Rate Source"),
    "temperature_source": ("fl_lib", "Temperature Source"),
    "thermal_reference": ("fl_lib", "Thermal Reference"),
    "temperature_sensor": ("fl_lib", "Temperature Sensor"),
    "heat_flow_sensor": ("fl_lib", "Heat Flow Rate Sensor"),
    "ps_simulink_converter": ("nesl_utility", "PS-Simulink Converter"),
    "to_workspace": ("simulink", "To Workspace"),
    "solver_configuration": ("nesl_utility", "Solver Configuration"),
}


class SimulationBuildCapabilityProbe:
    """Query only fixed MATLAB products, license features, and reviewed blocks.

    The probe has no user-controlled function, library, block name, path, or
    expression input. It never calls eval, feval, system, a solver, or save.
    """

    probe_version = "simulation-build-capabilities-v2"

    def probe(self, engine: object) -> dict[str, Any]:
        version = str(getattr(engine, "version")(nargout=1))
        products = _fixed_product_presence(engine)
        product_names = {item["name"].casefold() for item in products}
        product_report: dict[str, dict[str, Any]] = {}
        for key, (_query_name, _query_kind, product_name, feature) in _PRODUCT_FEATURES.items():
            installed = product_name.casefold() in product_names
            licensed = bool(getattr(engine, "license")("test", feature, nargout=1))
            product_report[key] = {
                "installed": installed,
                "licensed": licensed,
                "available": installed and licensed,
                "product_name": product_name,
                "license_feature": feature,
            }

        approved_blocks: dict[str, dict[str, Any]] = {}
        loaded: set[str] = set()
        if product_report["simscape"]["available"]:
            for component_type, (library, block_name) in _REVIEWED_BLOCK_QUERIES.items():
                if library not in loaded:
                    getattr(engine, "load_system")(library, nargout=0)
                    loaded.add(library)
                matches = getattr(engine, "find_system")(
                    library,
                    "LookUnderMasks", "all",
                    "FollowLinks", "on",
                    "Type", "Block",
                    "Name", block_name,
                    nargout=1,
                )
                paths = sorted({str(path) for path in _as_iterable(matches) if str(path).startswith(f"{library}/")})
                approved_blocks[component_type] = {
                    "available": len(paths) == 1,
                    "block_name": block_name,
                    "library": library,
                    "resolved_path": paths[0] if len(paths) == 1 else None,
                    "match_count": len(paths),
                }
        else:
            for component_type, (library, block_name) in _REVIEWED_BLOCK_QUERIES.items():
                approved_blocks[component_type] = {
                    "available": False,
                    "block_name": block_name,
                    "library": library,
                    "resolved_path": None,
                    "match_count": 0,
                }

        return {
            "probe_version": self.probe_version,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "matlab": {"available": True, "version": version},
            "simulink": product_report["simulink"],
            "simscape": product_report["simscape"],
            "simscape_fluids": product_report["simscape_fluids"],
            "domains": {
                "thermal": {
                    "available": product_report["simulink"]["available"] and product_report["simscape"]["available"],
                    "status": "available" if product_report["simulink"]["available"] and product_report["simscape"]["available"] else "CAPABILITY_NOT_AVAILABLE",
                },
                "isothermal_liquid": {
                    "available": product_report["simscape_fluids"]["available"],
                    "status": "available" if product_report["simscape_fluids"]["available"] else "CAPABILITY_NOT_AVAILABLE",
                },
            },
            "installed_products": products,
            "approved_blocks": approved_blocks,
            "security": {
                "fixed_queries_only": True,
                "accepts_user_code": False,
                "accepts_user_paths": False,
                "executes_simulation": False,
            },
        }


def _normalize_products(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _as_iterable(value):
        raw = _as_mapping(item)
        name = _field(raw, item, "Name")
        if not name:
            continue
        result.append({
            "name": name,
            "version": _field(raw, item, "Version"),
            "release": _field(raw, item, "Release"),
        })
    return sorted(result, key=lambda item: item["name"].casefold())


def _fixed_product_presence(engine: object) -> list[dict[str, str]]:
    products: list[dict[str, str]] = [{"name": "MATLAB", "version": "", "release": ""}]
    for query_name, query_kind, product_name, _feature in _PRODUCT_FEATURES.values():
        present = float(getattr(engine, "exist")(query_name, query_kind, nargout=1)) != 0.0
        if present:
            products.append({"name": product_name, "version": "", "release": ""})
    return sorted(products, key=lambda item: item["name"].casefold())


def _as_iterable(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field(mapping: Mapping[str, Any], value: Any, name: str) -> str:
    raw = mapping.get(name, mapping.get(name.casefold()))
    if raw is None:
        raw = getattr(value, name, getattr(value, name.casefold(), ""))
    return str(raw or "")


__all__ = ["SimulationBuildCapabilityProbe"]
