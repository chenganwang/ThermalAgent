from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os

from .index_manifest import sha256_file


def _candidate_hashes_valid(build: dict[str, Any]) -> tuple[bool, list[str]]:
    path_keys = {
        "faiss": "faiss_path",
        "faiss_meta": "faiss_meta_path",
        "bm25": "bm25_path",
        "bm25_meta": "bm25_meta_path",
        "mapping": "mapping_path",
        "chunk_manifest": "chunk_manifest_path",
    }
    mismatches: list[str] = []
    for hash_key, path_key in path_keys.items():
        path = Path(str(build.get(path_key) or ""))
        expected = str(build.get("hashes", {}).get(hash_key) or "")
        if not path.exists() or not expected or sha256_file(path) != expected:
            mismatches.append(hash_key)
    return not mismatches, mismatches


def activate_candidate(
    build: dict[str, Any],
    gate: dict[str, Any],
    active_manifest_path: str | Path,
    *,
    previous_version: str | None = None,
) -> dict[str, Any]:
    pointer = Path(active_manifest_path)
    if not bool(gate.get("activation_allowed")) or not bool(gate.get("passed")):
        return {
            "status": "blocked_by_release_gate",
            "activated": False,
            "activation_allowed": False,
            "active_manifest_modified": False,
        }
    binding = gate.get("candidate_binding") or {}
    if (binding.get("version") != build.get("version")
            or binding.get("evaluation_version") != build.get("version")
            or binding.get("hashes") != build.get("hashes")):
        return {
            "status": "blocked_release_evidence_candidate_mismatch", "activated": False,
            "activation_allowed": False, "active_manifest_modified": False,
        }
    hashes_valid, mismatches = _candidate_hashes_valid(build)
    if not hashes_valid:
        return {
            "status": "blocked_candidate_hash_mismatch",
            "activated": False,
            "activation_allowed": False,
            "hash_mismatches": mismatches,
            "active_manifest_modified": False,
        }

    previous_payload: dict[str, Any] = {}
    if pointer.exists():
        try:
            previous_payload = json.loads(pointer.read_text(encoding="utf-8"))
        except Exception:
            previous_payload = {}
    prior = previous_version or previous_payload.get("active_version")
    payload = {
        "active_version": build.get("version"),
        "previous_version": prior,
        "faiss_path": build.get("faiss_path"),
        "faiss_meta_path": build.get("faiss_meta_path"),
        "bm25_path": build.get("bm25_path"),
        "bm25_meta_path": build.get("bm25_meta_path"),
        "mapping_path": build.get("mapping_path"),
        "chunk_manifest_path": build.get("chunk_manifest_path"),
        "candidate_hashes": dict(build.get("hashes") or {}),
        "activated_at": datetime.now(timezone.utc).isoformat(),
        "activation_run_id": f"activate_{build.get('version')}",
        "rollback_available": bool(prior),
        "knowledge_units_included": False,
        "database_written": False,
    }
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_suffix(pointer.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, pointer)
    return {
        "status": "activated",
        "activated": True,
        "activation_allowed": True,
        "active_manifest_modified": True,
        "active_manifest_path": str(pointer.resolve()),
        "active_version": payload["active_version"],
        "previous_version": payload["previous_version"],
        "rollback_available": payload["rollback_available"],
    }
