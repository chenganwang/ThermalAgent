"""Small typed facade over the existing independent steady nodal solver."""
from __future__ import annotations

from math import fsum, isfinite
from services.engineering_service.result_identity import reference_calculation_fingerprint

from services.physics_service.contracts import EnergyBalance, PhysicsQuantity, PhysicsValidationRequest
from services.physics_service.validator import validate_physics
from services.simulation_service.modeling.thermal_network import build_layered_network
from services.simulation_service.modeling.thermal_network_solver import ThermalNetworkReferenceSolver

from .contracts import LayeredWallRequest, ReferenceHistory, ReferenceMetric, ReferenceResult


def solve_reference(request: LayeredWallRequest | dict) -> ReferenceResult:
    """Calculate supplied wall parameters; no LLM, files, DB, or external solver."""
    # Revalidate even a mutable Pydantic instance supplied by another caller.
    request = LayeredWallRequest.model_validate(request.model_dump() if isinstance(request, LayeredWallRequest) else request)
    base = {"inputs": request, "input_fingerprint": reference_calculation_fingerprint(request.model_dump())}
    try:
        resistances = [float(layer.thickness_m) / float(layer.conductivity_w_mk) / float(request.area_m2) for layer in request.layers]
        cells = [
            {"thickness_m": float(layer.thickness_m) / request.cells_per_layer,
             "conductivity_w_mk": float(layer.conductivity_w_mk), "area_m2": float(request.area_m2)}
            for layer in request.layers for _ in range(request.cells_per_layer)
        ]
        resistance = fsum(resistances)
        if not all(isfinite(value) and value > 0 for value in [resistance, *resistances]):
            raise ArithmeticError()
        analytic_heat = (request.left_temperature_k - request.right_temperature_k) / resistance
        model = build_layered_network(model_id="reference_layered_wall", layers=cells,
                                      hot_temperature_k=request.left_temperature_k, cold_temperature_k=request.right_temperature_k)
        raw = ThermalNetworkReferenceSolver().solve(model)
        if raw["status"] != "PASS":
            return ReferenceResult(**base, status="failed", reference_executed=True,
                                   errors=[{"code": raw.get("code", "REFERENCE_NOT_APPLICABLE"), "message": "The bounded nodal solver could not resolve this parameter set."}])
        points = [(0.0, float(request.left_temperature_k))]
        positions = []
        for index, cell in enumerate(cells, 1):
            positions.append(cell["thickness_m"])
            node = raw["port_nodes"][f"layer_{index}.B"]
            points.append((fsum(positions), raw["node_temperatures_k"][node]))
        flows = [raw["component_heat_flows_w"][f"layer_{index}"] for index in range(1, len(cells) + 1)]
        if not all(isfinite(value) for value in [analytic_heat, *flows, *[v for point in points for v in point]]):
            raise ArithmeticError()
        heat = flows[0]
        absolute_error = abs(heat - analytic_heat)
        heat_scale = max(abs(heat), abs(analytic_heat))
        relative_error = abs(heat / heat_scale - analytic_heat / heat_scale) if heat_scale else 0.0
        balance_scale = max(abs(value) for value in flows)
        local_imbalance = max((abs(left - right) for left, right in zip(flows, flows[1:])), default=0.0)
        local_relative = local_imbalance / balance_scale if balance_scale else 0.0
        if not all(isfinite(value) for value in (absolute_error, relative_error, local_imbalance, local_relative)):
            raise ArithmeticError()
        physical = validate_physics(PhysicsValidationRequest(
            quantities=[PhysicsQuantity(name=f"temperature_{i}", value=temperature, unit="K", quantity_type="absolute_temperature",
                                        minimum=min(request.left_temperature_k, request.right_temperature_k) - 1e-8,
                                        maximum=max(request.left_temperature_k, request.right_temperature_k) + 1e-8)
                        for i, (_, temperature) in enumerate(points)] + [PhysicsQuantity(name="heat_rate", value=heat, unit="W")],
            energy_balance=EnergyBalance(heat_input_w=flows[0], heat_output_w=flows[-1], relative_tolerance=1e-8, absolute_tolerance_w=1e-8),
        ))
        verified = physical.passed and (absolute_error <= 1e-8 or relative_error <= 1e-8) and (local_imbalance <= 1e-8 or local_relative <= 1e-8)
        return ReferenceResult(
            **base, status="completed" if verified else "failed", reference_executed=True,
            metrics=[ReferenceMetric(name="heat_rate", value=heat, unit="W"), ReferenceMetric(name="equivalent_resistance", value=resistance, unit="K/W")],
            histories=[ReferenceHistory(points=points)], layer_resistances_k_w=resistances, validation=physical,
            verification={"method": "independent_nodal_vs_series_resistance", "nodal_solver_version": raw["solver_version"],
                          "passed": verified, "cell_count": len(cells), "analytic_heat_rate_w": analytic_heat,
                          "heat_absolute_error_w": absolute_error, "heat_relative_error": relative_error,
                          "max_internal_energy_imbalance_w": local_imbalance, "max_internal_energy_relative_error": local_relative,
                          "absolute_tolerance_w": 1e-8, "relative_tolerance": 1e-8},
            errors=[] if verified else [{"code": "REFERENCE_VERIFICATION_FAILED", "message": "The reference result did not meet its physical or numerical checks."}],
        )
    except (ArithmeticError, ValueError, TypeError, KeyError):
        return ReferenceResult(**base, status="failed", reference_executed=True,
                               errors=[{"code": "REFERENCE_NUMERICAL_FAILURE", "message": "The parameter scales exceeded the stable finite numerical range."}])
