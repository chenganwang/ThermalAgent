from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from testing_profiles import PROFILES, select_profile
from testing_runtime import isolated_runtime
from testing_process import run_test_process

from services.retrieval_service.evaluation.test_manifest import (  # noqa: E402
    load_test_manifest,
    select_test_suite,
    summarize_manifest,
)


SUITES = ("quick", "contract", "database", "matlab-real", "full")
TIMEOUTS = {"fast": 120, "medium": 300, "slow": 900}


def _argv_for(item: dict[str, Any]) -> list[str]:
    command = str(item["command"])
    tokens = shlex.split(command, posix=False)
    if not tokens or tokens[0].lower() not in {"python", "python.exe"}:
        raise ValueError(f"manifest command must use the Python entrypoint: {command}")
    return [sys.executable, *tokens[1:]]


def run_selected_tests(
    suite: str,
    selected: list[dict[str, Any]],
    *,
    dry_run: bool,
    include_real_resources: bool,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failed = 0
    passed = 0
    skipped = 0
    started = time.perf_counter()
    for index, item in enumerate(selected):
        if item.get("requires_real_resource") and not include_real_resources:
            raise PermissionError(f"test requires --include-real-resources: {item['id']}")
        record = dict(item)
        if dry_run:
            record.update({"status": "dry_run", "exit_code": None, "duration_seconds": 0.0})
            results.append(record)
            continue
        command_started = time.perf_counter()
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / 'progress.json').write_text(json.dumps({'total': len(selected), 'finished': index, 'current': item['id'], 'passed': passed, 'failed': failed}), encoding='utf-8')
        timed_out = False
        stdout = stderr = ''
        exit_code = None
        try:
            completed = run_test_process(
                list(item['_argv']) if '_argv' in item else _argv_for(item),
                cwd=Path(item.get('_cwd') or cwd or PROJECT_ROOT), env=env,
                timeout=TIMEOUTS[str(item["estimated_speed"])],
            )
            exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
            status = "passed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            status = 'timed_out'
            stdout = exc.stdout.decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
            stderr = exc.stderr.decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        except OSError as exc:
            status = 'launch_failed'
            stderr = f'{type(exc).__name__}: {exc}'
        # A resource probe may exit zero while explicitly reporting it could
        # not run. Retain that outcome; it is never proof of solver acceptance.
        if status == 'passed':
            try:
                start = stdout.find('{')
                declared = json.loads(stdout[start:]) if start >= 0 else {}
                declared_status = str(declared.get('status', ''))
            except (ValueError, AttributeError):
                declared_status = ''
            if declared_status.startswith('skipped'):
                status = 'resource_unavailable'
                record['reported_status'] = declared_status
        record.update(
            {
                "status": status,
                "exit_code": exit_code,
                "duration_seconds": round(time.perf_counter() - command_started, 4),
                "stdout": stdout[-12000:], "stderr": stderr[-12000:], "timed_out": timed_out,
            }
        )
        results.append(record)
        if status == "passed":
            passed += 1
        elif status == 'resource_unavailable':
            skipped += 1
        else:
            failed += 1
        if output_dir:
            stem = f'{index + 1:03d}-{item["id"]}'
            (output_dir / f'{stem}.stdout.log').write_text(stdout, encoding='utf-8')
            (output_dir / f'{stem}.stderr.log').write_text(stderr, encoding='utf-8')
            (output_dir / f'{stem}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            (output_dir / 'progress.json').write_text(json.dumps({'total': len(selected), 'finished': index + 1, 'current': None, 'passed': passed, 'failed': failed}), encoding='utf-8')
            print(f'[{index + 1}/{len(selected)}] {status}: {item["id"]}', file=sys.stderr, flush=True)
    return {
        "suite": suite,
        "dry_run": dry_run,
        "include_real_resources": include_real_resources,
        "total": len(selected),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration_seconds": round(time.perf_counter() - started, 4),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select and run ThermalAgent tests from the resource-safe manifest.")
    parser.add_argument("--suite", choices=SUITES, default="quick")
    parser.add_argument('--profile', choices=PROFILES, help='Layered selection; offline includes every local test, including slow tests.')
    parser.add_argument('--output-dir', type=Path, help='New evidence directory; source is copied into its isolated workspace.')
    parser.add_argument('--node', help='Node executable for the frontend profile; otherwise locate node on PATH.')
    parser.add_argument('--test-id', action='append', help='Run an exact id from the selected suite/profile (repeatable).')
    parser.add_argument("--list", action="store_true", help="List manifest statistics and suite names without execution.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected commands without execution.")
    parser.add_argument(
        "--include-real-resources",
        action="store_true",
        help="Explicitly allow tests classified as database, real MATLAB, network, or frontend resource users.",
    )
    return parser


def _frontend_tests(project: Path, node: str | None, *, prepare: bool = True) -> list[dict[str, Any]]:
    executable = node or shutil.which('node')
    if not executable:
        raise ValueError('frontend profile needs installed Node; supply --node or add node to PATH')
    frontend = project.parent / 'thermal-frontend'
    dependencies = PROJECT_ROOT.parent / 'thermal-frontend/node_modules'
    if not dependencies.is_dir():
        raise ValueError('frontend dependencies are missing; install the existing lockfile separately')
    # Existing dependencies are shared; source, build output and test state stay
    # in the copied frontend. This does not install or update any package.
    if prepare:
        subprocess.run([executable, '-e', "require('fs').symlinkSync(process.argv[1],process.argv[2],'junction')", str(dependencies), str(frontend / 'node_modules')], check=True)
        # Dependency junctions are read-only inputs. Vite's caches and its
        # bundled configuration output both belong to this copied frontend.
        (frontend / 'vite.test.config.mjs').write_text(
            "import base from './vite.config.js';\nexport default async (env) => ({...(await (typeof base === 'function' ? base(env) : base)), cacheDir: '.test-vite-cache'});\n", encoding='utf-8')
    package = json.loads((frontend / 'package.json').read_text(encoding='utf-8'))
    commands = {
        'frontend_tests': [executable, *shlex.split(package['scripts']['test'])[1:]],
        'frontend_lint': [executable, 'node_modules/oxlint/bin/oxlint'],
        'frontend_build': [executable, 'node_modules/vite/bin/vite.js', 'build', '--config', 'vite.test.config.mjs', '--configLoader', 'runner'],
    }
    return [{'id': key, 'path': None, 'command': key, '_argv': argv, '_cwd': str(frontend), 'estimated_speed': 'slow', 'requires_real_resource': False} for key, argv in commands.items()]


def _write_report(output: Path, result: dict[str, Any]) -> None:
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# ThermalAgent test run', '', f"Selection: {result['suite']}", '',
             f"Executed **{result['total']}** scripts/commands: **{result['passed']} passed**, **{result['failed']} failed**, **{result.get('skipped', 0)} unavailable**.",
             '', 'Counts are script entrypoints, not individual assertions. Excluded resource tests are not passes.', '',
             '| Test | Result | Seconds |', '|---|---|---:|']
    lines += [f"| {row['id']} | {row['status']} | {row['duration_seconds']} |" for row in result['results']]
    excluded = result.get('excluded_tests') or []
    lines += ['', f'## Explicit exclusions ({len(excluded)})', '', '| Script | Reason |', '|---|---|']
    lines += [f"| {row['path']} | {row['reason']} |" for row in excluded]
    lines += ['', 'Full stdout/stderr and incremental progress are retained under `logs/`. No test is removed or relabeled as passed.']
    (output / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_test_manifest()
    if args.list:
        print(json.dumps({"suites": list(SUITES), 'profiles': list(PROFILES), "statistics": summarize_manifest(manifest)}, indent=2))
        return 0
    try:
        label = args.profile or args.suite
        if args.profile:
            selected, excluded = select_profile(manifest, args.profile, include_real_resources=args.include_real_resources)
            if args.profile == 'frontend':
                selected = _frontend_tests(PROJECT_ROOT, args.node, prepare=False)
                excluded = []
        else:
            selected = select_test_suite(manifest, args.suite, include_real_resources=args.include_real_resources)
            paths = {row.get('path') for row in selected}
            excluded = [{'path': row['path'], 'reason': 'outside legacy suite or resource/speed gate'} for row in manifest['tests'] if row['path'] not in paths]
        if args.test_id:
            requested = set(args.test_id)
            unknown = requested - {row['id'] for row in selected}
            if unknown:
                raise ValueError(f'Test ids unavailable in selected profile: {sorted(unknown)}')
            excluded.extend({'path': row.get('path') or row['id'], 'reason': 'outside explicit test-id selection'} for row in selected if row['id'] not in requested)
            selected = [row for row in selected if row['id'] in requested]
        if args.dry_run:
            result = run_selected_tests(label, selected, dry_run=True, include_real_resources=args.include_real_resources)
        else:
            output = (args.output_dir or PROJECT_ROOT / 'runtime/test_runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')).resolve()
            output.mkdir(parents=True, exist_ok=True)
            external = bool(args.include_real_resources and (args.profile == 'external' or not args.profile))
            with isolated_runtime(output, external=external) as (project, env, isolation):
                if args.profile == 'frontend':
                    selected = _frontend_tests(project, args.node)
                    if args.test_id:
                        selected = [row for row in selected if row['id'] in set(args.test_id)]
                result = run_selected_tests(label, selected, dry_run=False, include_real_resources=args.include_real_resources, cwd=project, env=env, output_dir=output / 'logs')
                result.update(isolation=isolation, excluded_tests=excluded, output_dir=str(output))
                _write_report(output, result)
        result['excluded_tests'] = excluded
    except (PermissionError, ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result["failed"] or result.get('skipped') else 0


if __name__ == "__main__":
    raise SystemExit(main())
