from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .contracts import DemoQAEvaluationResult, DemoQASummary


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "mvp" / "evaluation" / "outputs"


@dataclass(frozen=True)
class EvaluationReportPaths:
    eval_json: Path
    eval_markdown: Path
    failures_json: Path


def _metadata_coverage(results: list[DemoQAEvaluationResult]) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for result in results:
        status = result.response_summary.get("metadata_status")
        if isinstance(status, dict):
            for key in status:
                coverage[key] = coverage.get(key, 0) + 1
    return dict(sorted(coverage.items()))


def _report_payload(results: list[DemoQAEvaluationResult], summary: DemoQASummary) -> dict[str, Any]:
    forbidden_failures = sum(
        1 for result in results for failure in result.failures if failure.startswith("forbidden_claim:")
    )
    return {
        "benchmark": "ThermalAgent-DemoQA-50",
        "summary": summary.to_dict(),
        "forbidden_claims": {
            "failures": forbidden_failures,
            "pass_rate": summary.metric_scores.get("forbidden_claims_pass_rate", 0.0),
        },
        "metadata_coverage": _metadata_coverage(results),
        "self_critique_coverage": summary.metric_scores.get("self_critique_presence_rate", 0.0),
        "multi_agent_coverage": summary.metric_scores.get("multi_agent_trace_presence_rate", 0.0),
        "results": [result.to_dict() for result in results],
    }


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# ThermalAgent-DemoQA-50 Evaluation", "",
        "## Overall", "",
        f"- pass_rate: {summary['pass_rate']:.4f}",
        f"- average_score: {summary['average_score']:.2f}",
        f"- passed: {summary['passed']} / {summary['total']}", "",
        "## category_scores", "",
        "| Category | Passed | Total | Pass Rate | Average Score |", "|---|---:|---:|---:|---:|",
    ]
    for category, values in summary.get("category_scores", {}).items():
        lines.append(
            f"| `{category}` | {values['passed']} | {values['total']} | {values['pass_rate']:.4f} | {values['average_score']:.2f} |"
        )
    lines.extend(["", "## metric_scores", ""])
    for metric, value in summary.get("metric_scores", {}).items():
        lines.append(f"- {metric}: {value:.4f}")
    lines.extend(["", "## Metadata Coverage", ""])
    for key, count in payload.get("metadata_coverage", {}).items():
        lines.append(f"- `{key}`: {count}")
    lines.extend([
        "", "## Safety Coverage", "",
        f"- forbidden_claim_failures: {payload['forbidden_claims']['failures']}",
        f"- self_critique_coverage: {payload['self_critique_coverage']:.4f}",
        f"- multi_agent_coverage: {payload['multi_agent_coverage']:.4f}",
        "", "## Failure Cases", "",
        "| Case | Category | Score | Failures |", "|---|---|---:|---|",
    ])
    failed_results = [result for result in payload.get("results", []) if not result.get("passed")]
    if not failed_results:
        lines.append("| - | - | - | None |")
    else:
        for result in failed_results:
            failures = "; ".join(result.get("failures") or [])
            lines.append(f"| `{result['case_id']}` | `{result['category']}` | {result['score']:.1f} | {failures} |")
    lines.extend([
        "", "## Next Steps", "",
        "- Investigate repeated contract failures before changing business logic.",
        "- Keep quick (10-case) and full (50-case) gates separate in CI.",
    ])
    return "\n".join(lines) + "\n"


def write_evaluation_reports(
    results: list[DemoQAEvaluationResult],
    summary: DemoQASummary,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> EvaluationReportPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = EvaluationReportPaths(
        eval_json=output_dir / "thermalagent_demoqa_50_eval.json",
        eval_markdown=output_dir / "thermalagent_demoqa_50_eval.md",
        failures_json=output_dir / "thermalagent_demoqa_50_failures.json",
    )
    payload = _report_payload(results, summary)
    paths.eval_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths.eval_markdown.write_text(_markdown(payload), encoding="utf-8")
    failures = [result.to_dict() for result in results if not result.passed]
    paths.failures_json.write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths


__all__ = ["DEFAULT_OUTPUT_DIR", "EvaluationReportPaths", "write_evaluation_reports"]
