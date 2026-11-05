from __future__ import annotations

from pathlib import Path
import json
import math
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.tools.thermal_calculators import (
    conduction_resistance,
    coolant_temperature_rise,
    junction_temperature_estimate,
    liquid_flow_rate_required,
    required_thermal_resistance,
)
from services.retrieval_service.tools.tool_registry import run_detected_tool


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _close(actual: float | None, expected: float, *, tol: float = 1e-5) -> None:
    _assert(actual is not None, f"actual value is None, expected {expected}")
    _assert(math.isclose(float(actual), expected, rel_tol=tol, abs_tol=tol), f"{actual} != {expected}")


def _check_common(result: dict) -> None:
    _assert(result["status"] == "ok", f"expected ok, got {result}")
    _assert(bool(result.get("formula")), "formula must not be empty")
    _assert(bool(result.get("calculation_steps")), "calculation_steps must not be empty")
    _assert("warnings" in result, "warnings field must exist")
    _assert("unit_check" in result and result["unit_check"]["status"] == "passed", "unit check must pass")


def test_required_thermal_resistance() -> None:
    result = required_thermal_resistance(P_W=500, T_max_C=80, T_in_C=30)
    _check_common(result)
    _close(result["result"]["allowed_delta_T_K"], 50)
    _close(result["result"]["R_required_K_per_W"], 0.1)


def test_junction_temperature_estimate() -> None:
    result = junction_temperature_estimate(P_W=600, T_in_C=28, R_total_K_per_W=0.08)
    _check_common(result)
    _close(result["result"]["temperature_rise_K"], 48)
    _close(result["result"]["T_j_C"], 76)


def test_conduction_resistance() -> None:
    result = conduction_resistance(L_m=0.001, k_W_mK=6, A_m2=0.04 * 0.04)
    _check_common(result)
    _close(result["result"]["R_cond_K_per_W"], 0.1041667, tol=1e-4)


def test_coolant_temperature_rise() -> None:
    result = coolant_temperature_rise(Q_W=800, m_dot_kg_s=0.05, cp_J_kgK=4180)
    _check_common(result)
    _close(result["result"]["delta_T_K"], 800 / (0.05 * 4180), tol=1e-4)


def test_liquid_flow_rate_required() -> None:
    result = liquid_flow_rate_required(Q_W=800, cp_J_kgK=4180, delta_T_K=5, rho_kg_m3=1000)
    _check_common(result)
    _close(result["result"]["mass_flow_kg_s"], 0.0382775, tol=1e-5)
    _close(result["result"]["volume_flow_m3_s"], 3.82775e-5, tol=1e-6)
    _close(result["result"]["volume_flow_L_min"], 2.29665, tol=1e-4)


def test_invalid_input_returns_error() -> None:
    result = required_thermal_resistance(P_W=0, T_max_C=80, T_in_C=30)
    _assert(result["status"] == "error", f"invalid input should return error: {result}")
    _assert(result["error"], "error message must be present")
    _assert(result["unit_check"]["status"] == "failed", "unit check must fail for invalid input")


def test_agent_tool_detection_examples() -> None:
    examples = {
        "500W 芯片，入口水温 30℃，希望芯片不超过 80℃，需要多低的总热阻？": "required_thermal_resistance",
        "芯片功耗 600W，总热阻 0.08 K/W，入口水温 28℃，结温多少？": "junction_temperature_estimate",
        "导热垫厚度 1mm，导热系数 6 W/(m·K)，面积 40mm×40mm，导热热阻是多少？": "conduction_resistance",
        "800W 热负荷，水的比热容 4180 J/(kg·K)，允许温升 5K，需要多少 L/min 流量？": "liquid_flow_rate_required",
        "流量 0.05 kg/s，带走 800W 热量，水的比热容 4180 J/(kg·K)，冷却液温升多少？": "coolant_temperature_rise",
    }
    for query, tool_name in examples.items():
        result = run_detected_tool(query)
        _assert(result is not None, f"no tool detected for {query}")
        _assert(result["tool_name"] == tool_name, f"wrong tool for {query}: {result}")
        _assert(result["status"] == "ok", f"tool should run for {query}: {result}")


def main() -> None:
    tests = [
        test_required_thermal_resistance,
        test_junction_temperature_estimate,
        test_conduction_resistance,
        test_coolant_temperature_rise,
        test_liquid_flow_rate_required,
        test_invalid_input_returns_error,
        test_agent_tool_detection_examples,
    ]
    for test in tests:
        test()
    print(json.dumps({"status": "ok", "tests": [test.__name__ for test in tests]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
