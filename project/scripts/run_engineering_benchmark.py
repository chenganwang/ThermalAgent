"""Run the offline engineering acceptance catalog without production writes."""
import argparse
import os
from pathlib import Path
import sys

for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.engineering.runner import run_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/benchmarks/engineering"), help="Append a new run directory; never overwrite an existing run")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run selected case ID; repeat for multiple cases")
    args = parser.parse_args()
    output, report = run_benchmark(args.output_dir, args.case_ids)
    print(f"Engineering benchmark: {report['passed']}/{report['total']} passed; {report['failed']} failed")
    print(f"Report: {output / 'report.md'}")
    return 0 if not report["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
