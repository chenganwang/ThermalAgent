from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.demo_cases.registry import list_demo_cases
from services.retrieval_service.demo_cases.runner import run_demo_cases


RESULTS_PATH = ROOT / "docs" / "mvp" / "fixtures" / "demo_case_results.json"
SUMMARY_PATH = ROOT / "docs" / "mvp" / "fixtures" / "demo_case_summary.md"


def main() -> None:
    results = run_demo_cases(list_demo_cases())
    payload = [result.to_dict() for result in results]
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    passed = sum(1 for result in results if result.passed)
    lines = [
        "# Demo Case Summary", "", f"- Cases: {len(results)}", f"- Passed: {passed}",
        f"- Failed: {len(results) - passed}", "", "| Case | Status | Failures |", "|---|---|---|",
    ]
    for result in results:
        failure_text = "; ".join(result.failures) if result.failures else "-"
        lines.append(f"| `{result.case_id}` | {'PASS' if result.passed else 'FAIL'} | {failure_text} |")
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok" if passed == len(results) else "failed", "cases": len(results), "passed": passed}, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
