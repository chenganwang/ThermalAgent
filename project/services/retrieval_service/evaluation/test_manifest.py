from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "config" / "test_manifest.json"


def load_test_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("tests"), list):
        raise ValueError("unsupported or malformed test manifest")
    return payload


def discover_test_scripts(project_root: Path | str = PROJECT_ROOT) -> list[str]:
    root = Path(project_root)
    return sorted(path.relative_to(root).as_posix() for path in (root / "scripts").glob("test_*.py") if path.is_file())


def summarize_manifest_coverage(manifest: dict[str, Any], discovered: list[str]) -> dict[str, Any]:
    registered_paths = {
        str(record.get("path"))
        for record in manifest.get("tests", [])
        if isinstance(record, dict) and isinstance(record.get("path"), str)
    }
    discovered_paths = set(discovered)
    missing = sorted(discovered_paths - registered_paths)
    stale = sorted(registered_paths - discovered_paths)
    return {
        "total": len(discovered_paths),
        "registered": len(discovered_paths & registered_paths),
        "missing": missing,
        "stale": stale,
    }


def summarize_manifest(manifest: dict[str, Any], discovered: list[str] | None = None) -> dict[str, Any]:
    records = [record for record in manifest.get("tests", []) if isinstance(record, dict)]
    coverage = summarize_manifest_coverage(manifest, discovered or discover_test_scripts())
    return {
        **coverage,
        "quick": len(manifest.get("quick_suite", [])),
        "slow": sum(record.get("estimated_speed") == "slow" for record in records),
        "database": sum(bool(record.get("requires_database")) for record in records),
        "real_matlab": sum(record.get("category") == "matlab_real" for record in records),
        "frontend": sum(bool(record.get("requires_frontend")) for record in records),
        "optional": sum(record.get("category") == "optional" for record in records),
    }


def _selected_record(record: dict[str, Any], *, test_id: str | None = None, command: str | None = None) -> dict[str, Any]:
    selected = dict(record)
    selected["id"] = test_id or Path(str(record["path"])).stem.removeprefix("test_")
    selected["command"] = command or f"python {str(record['path']).replace('/', chr(92))}"
    return selected


def select_test_suite(
    manifest: dict[str, Any],
    suite: str,
    *,
    include_real_resources: bool = False,
) -> list[dict[str, Any]]:
    records = [record for record in manifest.get("tests", []) if isinstance(record, dict)]
    by_path = {str(record.get("path")): record for record in records}
    if suite == "quick":
        selected: list[dict[str, Any]] = []
        for item in manifest.get("quick_suite", []):
            if not isinstance(item, dict):
                continue
            if "path" in item:
                path = str(item["path"])
                record = by_path.get(path)
                if record is None:
                    raise ValueError(f"quick suite path is not registered: {path}")
                selected.append(_selected_record(record, test_id=str(item["id"])))
            else:
                selected.append(
                    {
                        "id": str(item["id"]),
                        "command": str(item["command"]),
                        "path": None,
                        "category": "smoke" if item["id"] == "agent_smoke" else "contract",
                        "resource_level": "none",
                        "estimated_speed": "fast",
                        "requires_database": False,
                        "requires_matlab": False,
                        "requires_network": False,
                        "requires_frontend": False,
                        "requires_real_resource": False,
                        "default_quick": True,
                        "enabled": True,
                        "description": "Legacy quick-suite preflight command.",
                    }
                )
        return selected

    if suite not in {"contract", "database", "matlab-real", "full"}:
        raise ValueError(f"unknown test suite: {suite}")
    if suite in {"database", "matlab-real"} and not include_real_resources:
        raise PermissionError(f"suite {suite} requires --include-real-resources")

    if suite == "contract":
        candidates = [record for record in records if record.get("category") == "contract"]
    elif suite == "database":
        candidates = [record for record in records if record.get("requires_database")]
    elif suite == "matlab-real":
        candidates = [record for record in records if record.get("category") == "matlab_real"]
    else:
        candidates = records

    selected = []
    for record in candidates:
        if not record.get("enabled", False):
            continue
        if suite in {"contract", "full"} and record.get("estimated_speed") == "slow":
            continue
        if record.get("requires_real_resource") and not include_real_resources:
            continue
        selected.append(_selected_record(record))
    return selected


__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "PROJECT_ROOT",
    "discover_test_scripts",
    "load_test_manifest",
    "select_test_suite",
    "summarize_manifest",
    "summarize_manifest_coverage",
]
