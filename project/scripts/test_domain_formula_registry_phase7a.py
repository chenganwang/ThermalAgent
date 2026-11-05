from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.domain_knowledge.formula_query import answer_formula_query
from services.retrieval_service.domain_knowledge.formula_registry import get_default_formula_registry


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_registry_loads_required_formula_set() -> None:
    registry = get_default_formula_registry()
    records = registry.list_formulas()
    _assert(len(records) >= 18, f"expected broad foundational formula set, got {len(records)}")
    _assert(not registry.validate(), f"registry validation errors: {registry.validate()}")


def test_formula_lookup_hits_core_queries() -> None:
    registry = get_default_formula_registry()
    cases = {
        "傅里叶导热定律的公式和参数含义是什么？": "fourier_law_conduction",
        "平壁稳态导热量公式": "plane_wall_conduction",
        "雷诺数定义是什么？": "reynolds_number",
        "Darcy-Weisbach pressure drop formula": "darcy_weisbach_pressure_drop",
        "Q = m_dot cp DeltaT 是什么公式": "coolant_energy_balance",
        "Prandtl number": "prandtl_number",
    }
    for query, expected in cases.items():
        record = registry.find_formula(query, task_type="formula")
        _assert(record is not None, f"no formula matched: {query}")
        _assert(record.formula_id == expected, f"wrong formula for {query}: {record.formula_id}")


def test_formula_answer_is_registry_based_and_provenance_aware() -> None:
    answer = answer_formula_query("雷诺数的定义是什么？它如何判断管内流动状态？")
    assert answer
    _assert("Re = rho * v * D_h / mu" in answer, f"Re formula missing: {answer}")
    _assert("2300" in answer and "4000" in answer, f"Re thresholds missing: {answer}")
    _assert("来源状态：pending" in answer, f"pending provenance not shown: {answer}")
    _assert("液冷资料" in answer or "chunk" in answer, f"retrieval boundary missing: {answer}")
    _assert("CDU" not in answer and "冷板液冷系统通常由" not in answer, f"generic liquid-cooling answer leaked: {answer}")


def test_tool_mapping_is_explicit_not_inferred() -> None:
    registry = get_default_formula_registry()
    mapped = registry.get_formula("plane_wall_conduction")
    unmapped = registry.get_formula("reynolds_number")
    _assert(mapped is not None and mapped.tool_id == "plane_wall_conduction", f"plane wall tool map missing: {mapped}")
    _assert(unmapped is not None and unmapped.tool_id is None, f"Re should not pretend to have a calculator: {unmapped}")


def main() -> None:
    tests = [
        test_registry_loads_required_formula_set,
        test_formula_lookup_hits_core_queries,
        test_formula_answer_is_registry_based_and_provenance_aware,
        test_tool_mapping_is_explicit_not_inferred,
    ]
    for test in tests:
        test()
    print(json.dumps({"status": "ok", "tests": [test.__name__ for test in tests]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
