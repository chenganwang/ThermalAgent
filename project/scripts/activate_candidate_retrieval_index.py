from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.indexing.index_activator import activate_candidate  # noqa: E402
from services.retrieval_service.indexing.release_gate import evaluate_release_gate  # noqa: E402
from services.retrieval_service.indexing.rollback import verify_rollback_snapshot  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


def markdown(title: str, payload: dict) -> str:
    lines = [f"# {title}", ""]
    for key in (
        "passed", "activation_allowed", "reason", "status", "activated",
        "rollback_verified", "rollback_dry_run_verified", "snapshot_hashes_valid",
        "old_production_hashes_unchanged",
    ):
        if key in payload:
            lines.append(f"- {key}: {payload.get(key)}")
    if payload.get("failed_conditions"):
        lines.extend(["", "## Failed Conditions", ""])
        lines.extend(f"- {item}" for item in payload["failed_conditions"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Release-gated atomic retrieval index activation")
    parser.add_argument("--contracts-passed", action="store_true")
    args = parser.parse_args()
    output = ROOT / "runtime/index_upgrade"
    old_eval = json.loads((output / "holdout_old_index_eval.json").read_text(encoding="utf-8"))
    candidate_eval = json.loads((output / "holdout_candidate_index_eval.json").read_text(encoding="utf-8"))
    validation = json.loads((output / "candidate_index_validation.json").read_text(encoding="utf-8"))
    snapshot = json.loads((output / "old_index_snapshot_manifest.json").read_text(encoding="utf-8"))
    build = json.loads((output / "candidate/current_build.json").read_text(encoding="utf-8"))
    checks = {
        "sources_schema": args.contracts_passed,
        "retrieval_count": args.contracts_passed,
        "agent_answer": args.contracts_passed,
        "quick_regression": args.contracts_passed,
        "retrieval_smoke": args.contracts_passed,
    }
    gate = evaluate_release_gate(old_eval, candidate_eval, validation, snapshot, checks)
    write_json(output / "release_gate.json", gate)
    (output / "release_gate.md").write_text(markdown("Retrieval Index Release Gate", gate), encoding="utf-8")

    activation = activate_candidate(
        build,
        gate,
        output / "active_index_manifest.json",
        previous_version=snapshot.get("index_version"),
    )
    write_json(output / "activation_result.json", activation)
    if activation.get("activated"):
        post = {
            "status": "pending_post_activation_verification",
            "activation_performed": True,
            "active_version": activation.get("active_version"),
        }
    else:
        post = {
            "status": "skipped_release_gate_blocked",
            "activation_performed": False,
            "active_version": snapshot.get("index_version"),
            "candidate_version": build.get("version"),
            "reason": gate.get("reason"),
            "agent_end_to_end_candidate_activation_tested": False,
            "production_index_unchanged": True,
        }
    write_json(output / "post_activation_verification.json", post)
    (output / "post_activation_verification.md").write_text(
        markdown("Post-Activation Verification", post), encoding="utf-8"
    )

    rollback = verify_rollback_snapshot(snapshot, activation_performed=bool(activation.get("activated")))
    write_json(output / "rollback_verification.json", rollback)
    (output / "rollback_verification.md").write_text(
        markdown("Retrieval Index Rollback Verification", rollback), encoding="utf-8"
    )
    print(
        f"gate_passed={gate['passed']} activation_allowed={gate['activation_allowed']} "
        f"activated={activation.get('activated')} rollback_dry_run={rollback['rollback_dry_run_verified']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
