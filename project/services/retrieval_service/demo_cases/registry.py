from __future__ import annotations

import json
from pathlib import Path

from .contracts import DemoCase


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_CASE_DIR = PROJECT_ROOT / "docs" / "mvp" / "demo_cases"


def list_demo_cases() -> list[DemoCase]:
    cases: list[DemoCase] = []
    for path in sorted(DEMO_CASE_DIR.glob("case_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases.append(DemoCase.from_dict(payload))
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("demo case_id values must be unique")
    return cases


def get_demo_case(case_id: str) -> DemoCase | None:
    return next((case for case in list_demo_cases() if case.case_id == case_id), None)


__all__ = ["DEMO_CASE_DIR", "get_demo_case", "list_demo_cases"]
