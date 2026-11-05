from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from .hydraulic_network_contracts import FlowDistributionResult


NETWORK_FORMULA = "series: dp_total=sum(dp_i); parallel: Q_i=Q_total*R_i^(-1/n)/sum(R_j^(-1/n)); dp_i=R_i*Q_i^n"


def json_safe_network(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe_network(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_network(item) for item in value]
    return value


def validate_network_inputs(network: dict[str, Any]) -> None:
    """Validate the actual supplied quantities without inventing missing data."""
    if not isinstance(network, dict):
        raise ValueError("network must be an object")

    def number(name, value, *, zero_allowed=False):
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{name} must be a finite number") from None
        if isinstance(value, bool) or not math.isfinite(parsed) or (parsed < 0 if zero_allowed else parsed <= 0):
            raise ValueError(f"{name} must be finite and {'non-negative' if zero_allowed else 'positive'}; booleans are not accepted")

    for key in ("total_flow_rate_lpm", "total_flow_rate_m3_s"):
        if network.get(key) is not None:
            number(key, network[key])
    if network.get("total_flow_rate_lpm") is not None and network.get("total_flow_rate_m3_s") is not None and not math.isclose(
        float(network["total_flow_rate_lpm"]) / 60000, float(network["total_flow_rate_m3_s"]), rel_tol=1e-9, abs_tol=0
    ):
        raise ValueError("total flow rate units specify conflicting values")
    for key in ("branches", "components"):
        items = network.get(key)
        if items is None:
            continue
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError(f"{key} must be an array of component objects")
        for index, item in enumerate(items):
            for field in ("resistance_coefficient", "resistance_exponent", "pressure_drop_pa", "flow_rate_lpm", "flow_rate_m3_s"):
                if item.get(field) is not None:
                    number(f"{key}.{index}.{field}", item[field], zero_allowed=field == "pressure_drop_pa")


def _validate_outputs(result: FlowDistributionResult) -> None:
    def finite_tree(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                raise ValueError("Network calculation exceeded the finite numerical range")
        elif isinstance(value, dict):
            for item in value.values():
                finite_tree(item)
        elif isinstance(value, list):
            for item in value:
                finite_tree(item)
    finite_tree(result.to_dict())
    for branch in result.branches:
        if branch.get("flow_rate_m3_s") is not None and branch["flow_rate_m3_s"] <= 0:
            raise ValueError("Computed branch flow underflowed the positive numerical range")
        if branch.get("resistance_coefficient") is not None and branch.get("pressure_drop_pa") is not None and branch["pressure_drop_pa"] <= 0:
            raise ValueError("Computed resistance pressure drop underflowed the positive numerical range")
    if result.topology == "parallel" and result.total_flow_rate_m3_s is not None:
        actual = math.fsum(branch["flow_rate_m3_s"] for branch in result.branches)
        if not math.isclose(actual, result.total_flow_rate_m3_s, rel_tol=1e-10, abs_tol=0):
            raise ValueError("Computed branch flows do not conserve total flow")
        drops = [branch["pressure_drop_pa"] for branch in result.branches if branch.get("pressure_drop_pa") is not None]
        if drops and any(not math.isclose(value, drops[0], rel_tol=1e-10, abs_tol=0) for value in drops):
            raise ValueError("Computed parallel branches do not share a common pressure drop")


def _flow_m3_s(data: dict[str, Any]) -> float | None:
    if data.get("total_flow_rate_m3_s") is not None:
        return float(data["total_flow_rate_m3_s"])
    if data.get("total_flow_rate_lpm") is not None:
        return float(data["total_flow_rate_lpm"]) / 60000.0
    return None


def _imbalance(branches: list[dict[str, Any]]) -> float | None:
    flows = [float(b["flow_rate_lpm"]) for b in branches if b.get("flow_rate_lpm") is not None]
    if len(flows) != len(branches) or not flows:
        return None
    avg = sum(flows) / len(flows)
    return None if avg == 0 else (max(flows) - min(flows)) / avg


def _result(status: str, topology: str, **kwargs: Any) -> FlowDistributionResult:
    return FlowDistributionResult(status=status, topology=topology, formula=NETWORK_FORMULA, **kwargs)


def calculate_network_flow_distribution(network: dict[str, Any]) -> FlowDistributionResult:
    try:
        validate_network_inputs(network)
        result = _calculate_network_flow_distribution(network)
        if result.status == "success":
            _validate_outputs(result)
        return result
    except (TypeError, ValueError, ArithmeticError):
        topology = str(network.get("topology") or "unknown").lower() if isinstance(network, dict) else "unknown"
        return _result("failed", topology if topology in {"series", "parallel", "mixed"} else "unknown",
                       error="Invalid, conflicting, or numerically unstable hydraulic inputs; no validated network estimate was produced.")


def _calculate_network_flow_distribution(network: dict[str, Any]) -> FlowDistributionResult:
    data = deepcopy(network or {})
    topology = str(data.get("topology") or "unknown").lower()
    if topology not in {"series", "parallel"}:
        return _result("missing_params" if topology == "unknown" else "unsupported", topology if topology in {"mixed", "unknown"} else "unknown", missing_parameters=["topology"])
    branches = deepcopy(data.get("branches") or [])
    components = deepcopy(data.get("components") or [])
    total_q = _flow_m3_s(data)
    total_lpm = total_q * 60000.0 if total_q is not None else None
    assumptions = list(data.get("assumptions") or [])
    warnings = list(data.get("warnings") or [])

    if topology == "series":
        items = components or branches
        if not items:
            return _result("missing_params", topology, missing_parameters=["components"])
        calculated: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            row = deepcopy(item)
            pressure = row.get("pressure_drop_pa")
            if pressure is None:
                resistance = row.get("resistance_coefficient")
                exponent = row.get("resistance_exponent")
                if resistance is None or exponent is None or total_q is None:
                    return _result("missing_params", topology, missing_parameters=[f"component_{index}_pressure_drop_or_resistance_and_total_flow"])
                pressure = float(resistance) * total_q ** float(exponent)
            row["pressure_drop_pa"] = float(pressure)
            if total_q is not None:
                row["flow_rate_m3_s"] = total_q
                row["flow_rate_lpm"] = total_lpm
            calculated.append(row)
        total_pressure = sum(float(row["pressure_drop_pa"]) for row in calculated)
        return _result("success", topology, total_flow_rate_lpm=total_lpm, total_flow_rate_m3_s=total_q,
            total_pressure_drop_pa=total_pressure, total_pressure_drop_kpa=total_pressure/1000.0,
            branches=calculated, flow_imbalance_ratio=0.0 if total_q is not None else None,
            steps=["Apply the same flow to each series component.", "Sum component pressure drops."], assumptions=assumptions, warnings=warnings)

    if not branches:
        return _result("missing_params", topology, total_flow_rate_lpm=total_lpm, total_flow_rate_m3_s=total_q, missing_parameters=["branches"])
    if total_q is None:
        return _result("missing_params", topology, branches=branches, missing_parameters=["total_flow_rate_lpm_or_total_flow_rate_m3_s"])
    explicit_identical = "identical_branches_explicit" in assumptions and len({b.get("identical_group_id") for b in branches}) == 1 and branches[0].get("identical_group_id")
    if explicit_identical:
        per_flow = total_q / len(branches)
        for row in branches:
            row["flow_rate_m3_s"] = per_flow
            row["flow_rate_lpm"] = per_flow * 60000.0
        for warning in (
            "equal_split_assumption",
            "idealized_identical_parallel_branches",
            "manifold_maldistribution_not_modeled",
            "manufacturing_variation_not_modeled",
            "local_resistance_differences_not_modeled",
            "one_dimensional_estimate_not_cfd_or_experiment",
        ):
            if warning not in warnings:
                warnings.append(warning)
        if "equal_split_assumption" not in assumptions:
            assumptions.append("equal_split_assumption")
        return _result("success", topology, total_flow_rate_lpm=total_lpm, total_flow_rate_m3_s=total_q,
            branches=branches, flow_imbalance_ratio=0.0, warnings=warnings, assumptions=assumptions,
            steps=["Apply explicit identical-branch equal split."])

    if any(b.get("resistance_coefficient") is None or b.get("resistance_exponent") is None for b in branches):
        return _result("missing_params", topology, total_flow_rate_lpm=total_lpm, total_flow_rate_m3_s=total_q,
            branches=branches, missing_parameters=["branch_resistance_or_identical_assumption"])
    exponents = {float(b["resistance_exponent"]) for b in branches}
    if len(exponents) != 1:
        return _result("unsupported", topology, total_flow_rate_lpm=total_lpm, total_flow_rate_m3_s=total_q,
            branches=branches, warnings=["different_resistance_exponents_require_a_numerical_solver"])
    exponent = exponents.pop()
    if exponent <= 0 or any(float(b["resistance_coefficient"]) <= 0 for b in branches):
        return _result("failed", topology, branches=branches, error="resistance coefficients and exponent must be positive")
    weights = [float(b["resistance_coefficient"]) ** (-1.0/exponent) for b in branches]
    denominator = sum(weights)
    for row, weight in zip(branches, weights):
        branch_q = total_q * weight / denominator
        row["flow_rate_m3_s"] = branch_q
        row["flow_rate_lpm"] = branch_q * 60000.0
        row["pressure_drop_pa"] = float(row["resistance_coefficient"]) * branch_q**exponent
    common = sum(float(b["pressure_drop_pa"]) for b in branches) / len(branches)
    return _result("success", topology, total_flow_rate_lpm=total_lpm, total_flow_rate_m3_s=total_q,
        common_pressure_drop_pa=common, total_pressure_drop_pa=common, total_pressure_drop_kpa=common/1000.0,
        branches=branches, flow_imbalance_ratio=_imbalance(branches), assumptions=assumptions, warnings=warnings,
        steps=["Convert total flow to SI units.", "Distribute flow by branch resistance weights.", "Verify a common parallel pressure drop."])


def liquid_network_flow_distribution(**kwargs: Any) -> dict[str, Any]:
    result = calculate_network_flow_distribution(kwargs.get("network") or kwargs)
    payload = result.to_dict()
    return {"tool_name":"liquid_network_flow_distribution","status":"ok" if result.status=="success" else "error",
        "network_status":result.status,"inputs":json_safe_network(kwargs),"formula":result.formula,"calculation_steps":result.steps,
        "result":payload,"warnings":result.warnings,"assumptions":result.assumptions,
        "missing_parameters":result.missing_parameters,"error":result.error,
        "engineering_note":"One-dimensional equivalent-network estimate/preparation only; not CFD or experimental data."}


__all__=["NETWORK_FORMULA","calculate_network_flow_distribution","liquid_network_flow_distribution"]
