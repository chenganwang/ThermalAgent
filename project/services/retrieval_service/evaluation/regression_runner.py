from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from .regression_contracts import RegressionTestItem


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class RegressionRunResult:
    suite: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    failures: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_suite(suite_name: str) -> list[RegressionTestItem]:
    from .regression_suites import get_suite

    return list(get_suite(suite_name))


def run_suite(
    suite_name: str,
    *,
    dry_run: bool = False,
    include_slow: bool = False,
    fail_fast: bool = False,
) -> RegressionRunResult:
    items = list_suite(suite_name)
    result = RegressionRunResult(suite=suite_name, total=len(items))
    started = time.perf_counter()
    for item in items:
        record = item.to_dict()
        if item.slow and not include_slow and suite_name != "slow_regression":
            record.update({"status": "skipped", "exit_code": None, "stdout": "", "stderr": ""})
            result.results.append(record)
            result.skipped += 1
            continue
        script_match = re.search(r"python\s+(scripts[\\/][^\s]+\.py)", item.command, flags=re.IGNORECASE)
        if script_match and not (PROJECT_ROOT / script_match.group(1)).is_file() and not item.required:
            record.update({"status": "skipped_missing_optional", "exit_code": None, "stdout": "", "stderr": ""})
            result.results.append(record)
            result.skipped += 1
            result.warnings.append(f"optional test not found: {script_match.group(1)}")
            continue
        if dry_run:
            record.update({"status": "dry_run", "exit_code": None, "stdout": "", "stderr": ""})
            result.results.append(record)
            result.skipped += 1
            continue
        command_started = time.perf_counter()
        try:
            completed = subprocess.run(
                item.command,
                cwd=PROJECT_ROOT,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=item.timeout_seconds,
            )
            record.update({
                "status": "passed" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-12000:],
                "stderr": completed.stderr[-12000:],
                "duration_seconds": round(time.perf_counter() - command_started, 4),
            })
        except subprocess.TimeoutExpired as exc:
            record.update({
                "status": "failed", "exit_code": None,
                "stdout": str(exc.stdout or "")[-12000:], "stderr": "timeout",
                "duration_seconds": round(time.perf_counter() - command_started, 4),
            })
        result.results.append(record)
        if record["status"] == "passed":
            result.passed += 1
        else:
            result.failed += 1
            result.failures.append(record)
            if fail_fast:
                break
    result.duration_seconds = round(time.perf_counter() - started, 4)
    return result


def write_regression_report(result: RegressionRunResult, output_path: Path | str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "RegressionRunResult", "RegressionTestItem", "list_suite", "run_suite", "write_regression_report",
]
