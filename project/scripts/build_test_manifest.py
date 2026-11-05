from __future__ import annotations

import ast
import json
from pathlib import Path
from testing_profiles import layers_for


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "config" / "test_manifest.json"

QUICK_SUITE = [
    {"id": "compileall", "command": "python -m compileall -q services scripts cli.py"},
    {"id": "agent_answer_contract", "path": "scripts/test_agent_answer_contract.py"},
    {"id": "agent_smoke", "command": "python scripts\\smoke_test_agent.py"},
    {"id": "task_service", "path": "scripts/test_task_understanding_service.py"},
    {"id": "task_regression", "path": "scripts/test_task_understanding_regression.py"},
    {"id": "demoqa_smoke", "path": "scripts/test_demoqa_evaluation_smoke.py"},
    {"id": "thermal_calculators", "path": "scripts/test_thermal_calculators.py"},
]
QUICK_PATHS = {item["path"] for item in QUICK_SUITE if "path" in item}

DATABASE_RESOURCE_MARKERS = (
    "audit_old_index(",
    "build_candidate_chunk_manifest(",
    "build_candidate_indexes(",
    "build_old_bundle(",
    "plan_candidate_build(",
    "selectonlychunkstore(",
    "snapshot_old_index(",
    "validate_candidate_index(",
)

# Audited dependency-boundary fixtures call the real index/review functions but
# supply temporary storage and SELECT-only synthetic stores. The static marker
# heuristic otherwise mistakes the function calls for a live database need.
# Keep this small and explicit: new tests remain conservatively classified.
LOCAL_FIXTURE_REASONS = {
    'test_bm25_tokenizer_contract': 'Real BM25/FAISS in temporary files with patched SELECT-only synthetic stores and deterministic embeddings; no database or model connection.',
    'test_index_rollback': 'Temporary snapshot files and explicit audit/mapping fixture; no database connection.',
    'test_no_old_index_deletion': 'Temporary byte/hash snapshot fixture; no database connection.',
    'test_no_ku_production_fusion': 'Temporary FAISS/BM25 plus SELECT-only synthetic store and deterministic embeddings.',
    'test_retrieval_diagnostics_artifacts': 'Temporary artifacts from the real CLI/pipeline with explicit FakeRuntime and store boundaries.',
}


def _imports_network_client(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return True
    network_roots = {"httpx", "requests", "urllib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in network_roots for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in network_roots:
            return True
    return False


def _classify(path: Path) -> dict[str, object]:
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    name = path.stem.lower()
    try:
        source = path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        source = ""
    requires_matlab = "matlab" in name and any(
        marker in name for marker in ("real", "connection", "host_validation", "diagnostic")
    )
    requires_database = any(
        marker in name
        for marker in (
            "database",
            "_db_",
            "readback",
            "write_",
            "atomicity",
            "activation",
            "post_activation",
            "migration",
        )
    ) or any(marker in source for marker in DATABASE_RESOURCE_MARKERS)
    if name in LOCAL_FIXTURE_REASONS:
        requires_database = False
    requires_frontend = "frontend" in name
    requires_network = _imports_network_client(path) or "real_eval" in name
    requires_real_resource = requires_database or requires_matlab or requires_network or requires_frontend

    if requires_matlab:
        category = "matlab_real"
    elif "matlab" in name:
        category = "matlab_mock"
    elif requires_database:
        category = "database"
    elif requires_frontend:
        category = "frontend"
    elif requires_network:
        category = "optional"
    elif any(marker in name for marker in (
        "calculation_chain", "dev_launcher_reuse_logic", "data_asset_randomized_properties",
    )):
        category = "slow"
    elif "data_asset_d2_bdd" in name:
        category = "integration"
    elif any(marker in name for marker in ("demoqa", "evaluation", "holdout", "score_analysis", "shadow_evaluation")):
        category = "evaluation"
    elif any(marker in name for marker in (
        "contract", "randomized", "schema", "facade", "readiness", "manifest", "no_known_import_cycles",
        "data_asset", "safe_source_projection",
    )):
        category = "contract"
    elif "regression" in name:
        category = "regression"
    elif "integration" in name or "workflow" in name or "pipeline" in name or "bdd" in name:
        category = "integration"
    else:
        category = "unit"

    if requires_database:
        resource_level = "database"
    elif requires_matlab:
        resource_level = "matlab"
    elif requires_network:
        resource_level = "external"
    elif requires_frontend:
        resource_level = "local"
    else:
        resource_level = "none"

    if category in {"slow", "matlab_real"} or requires_network:
        estimated_speed = "slow"
    elif category in {"database", "evaluation", "frontend", "integration"}:
        estimated_speed = "medium"
    else:
        estimated_speed = "fast"

    description = "Validates " + name.removeprefix("test_").replace("_", " ") + "."
    return {
        "path": relative,
        "category": category,
        "resource_level": resource_level,
        "estimated_speed": estimated_speed,
        "requires_database": requires_database,
        "requires_matlab": requires_matlab,
        "requires_network": requires_network,
        "requires_frontend": requires_frontend,
        "requires_real_resource": requires_real_resource,
        "default_quick": relative in QUICK_PATHS,
        "enabled": True,
        "description": description,
        **({'local_fixture_reason': LOCAL_FIXTURE_REASONS[name]} if name in LOCAL_FIXTURE_REASONS else {}),
    }


def build_manifest() -> dict[str, object]:
    tests = [_classify(path) for path in sorted((PROJECT_ROOT / "scripts").glob("test_*.py")) if path.is_file()]
    for record in tests:
        record['layers'] = layers_for(record)
    return {
        "schema_version": 1,
        "classification_policy": "conservative_static_v1_with_local_layers",
        "quick_suite": QUICK_SUITE,
        "tests": tests,
    }


def main() -> None:
    payload = build_manifest()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(OUTPUT_PATH), "tests": len(payload["tests"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
