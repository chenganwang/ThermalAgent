from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.evaluation.demoqa_dataset import load_demoqa_dataset
from services.retrieval_service.evaluation.report import DEFAULT_OUTPUT_DIR, write_evaluation_reports
from services.retrieval_service.evaluation.runner import run_demoqa_dataset, summarize_results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ThermalAgent-DemoQA-50 offline.")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N selected cases.")
    parser.add_argument("--category", default=None, help="Run only one category.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fail-under-score", type=float, default=None, help="Exit 1 below this 0-100 average score.")
    parser.add_argument("--fail-under-pass-rate", type=float, default=None, help="Exit 1 below this 0-1 pass rate.")
    args = parser.parse_args()

    items = load_demoqa_dataset()
    if args.category:
        items = [item for item in items if item.category == args.category]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        items = items[: args.limit]
    if not items:
        parser.error("no DemoQA items matched the requested filters")

    results = run_demoqa_dataset(items)
    summary = summarize_results(results)
    paths = write_evaluation_reports(results, summary, output_dir=args.output_dir)
    print(json.dumps({
        "benchmark": "ThermalAgent-DemoQA-50",
        "selected_cases": len(items),
        "category": args.category,
        "summary": summary.to_dict(),
        "outputs": {
            "eval_json": str(paths.eval_json),
            "eval_markdown": str(paths.eval_markdown),
            "failures_json": str(paths.failures_json),
        },
    }, ensure_ascii=False, indent=2))

    threshold_failed = False
    if args.fail_under_score is not None and summary.average_score < args.fail_under_score:
        threshold_failed = True
    if args.fail_under_pass_rate is not None and summary.pass_rate < args.fail_under_pass_rate:
        threshold_failed = True
    if threshold_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
