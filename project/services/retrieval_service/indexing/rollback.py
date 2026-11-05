from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime, timezone
import json
import os

from ..config import AppConfig

from .index_manifest import sha256_file


def rollback_to_snapshot(cfg: AppConfig, snapshot: dict[str, Any], active_manifest_path: str | Path,
                         *, expected_active_version: str) -> dict[str, Any]:
    """Atomically select verified old artifacts and their exported mapping.

    This restores the live read generation without deleting candidates or
    modifying either production artifacts or the legacy embeddings table.
    """
    pointer = Path(active_manifest_path)
    current = json.loads(pointer.read_text(encoding="utf-8"))
    if current.get("active_version") != expected_active_version:
        return {"rolled_back": False, "status": "blocked_active_version_changed"}
    required = {
        "faiss": cfg.paths.faiss_index_path, "faiss_meta": cfg.paths.faiss_meta_path,
        "bm25": cfg.paths.bm25_corpus_path, "bm25_meta": cfg.paths.bm25_meta_path,
    }
    files = {str(Path(item["source_path"]).resolve()): item for item in snapshot.get("files") or []}
    paths: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for role, source in required.items():
        item = files.get(str(source.resolve())) or {}
        backup = Path(str(item.get("snapshot_path") or ""))
        expected_hash = item.get("snapshot_sha256")
        if not backup.is_file() or not expected_hash or sha256_file(backup) != expected_hash:
            return {"rolled_back": False, "status": "blocked_snapshot_hash_mismatch", "artifact": role}
        paths[role + "_path"] = str(backup.resolve())
        hashes[role] = str(expected_hash)
    mapping = Path(str(snapshot.get("mapping_path") or ""))
    if not mapping.is_file() or sha256_file(mapping) != snapshot.get("mapping_sha256"):
        return {"rolled_back": False, "status": "blocked_snapshot_mapping_mismatch"}
    hashes["mapping"] = str(snapshot["mapping_sha256"])
    payload = {
        "mode": "legacy_snapshot", "active_version": snapshot["index_version"],
        "previous_version": expected_active_version, **paths, "mapping_path": str(mapping.resolve()),
        "candidate_hashes": hashes, "activated_at": datetime.now(timezone.utc).isoformat(),
        "database_written": False, "knowledge_units_included": False,
    }
    temporary = pointer.with_suffix(pointer.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, pointer)
    return {"rolled_back": True, "status": "rolled_back", "active_version": payload["active_version"],
            "database_written": False, "production_files_modified": False}


def verify_rollback_snapshot(
    snapshot: dict[str, Any],
    *,
    activation_performed: bool,
    rollback_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot_valid = True
    production_unchanged = True
    missing_files: list[str] = []
    hash_mismatches: list[str] = []
    for item in snapshot.get("files") or []:
        source = Path(str(item.get("source_path") or ""))
        backup = Path(str(item.get("snapshot_path") or ""))
        if not source.exists() or not backup.exists():
            missing_files.append(str(source if not source.exists() else backup))
            snapshot_valid = False
            production_unchanged = False
            continue
        source_hash = sha256_file(source)
        backup_hash = sha256_file(backup)
        if backup_hash != str(item.get("snapshot_sha256") or ""):
            snapshot_valid = False
            hash_mismatches.append(f"snapshot:{backup.name}")
        if source_hash != str(item.get("source_sha256") or ""):
            production_unchanged = False
            hash_mismatches.append(f"production:{source.name}")
    mapping = Path(str(snapshot.get("mapping_path") or ""))
    if not mapping.is_file() or sha256_file(mapping) != snapshot.get("mapping_sha256"):
        snapshot_valid = False
        hash_mismatches.append("snapshot:chunk_mapping")
    dry_run_verified = snapshot_valid and production_unchanged and not missing_files and bool(snapshot.get("files"))
    switch_verified = bool(
        activation_performed and dry_run_verified and rollback_receipt
        and rollback_receipt.get("rolled_back")
        and rollback_receipt.get("active_version") == snapshot.get("index_version")
    )
    return {
        "rollback_verified": switch_verified,
        "rollback_dry_run_verified": dry_run_verified,
        "reason": (
            "rollback_switch_cycle_verified" if switch_verified
            else "activation_not_performed_release_gate_blocked" if not activation_performed
            else "rollback_switch_not_performed" if dry_run_verified
            else "rollback_snapshot_validation_failed"
        ),
        "snapshot_hashes_valid": snapshot_valid,
        "old_production_hashes_unchanged": production_unchanged,
        "missing_files": missing_files,
        "hash_mismatches": hash_mismatches,
        "old_index_deleted": False,
        "database_written": False,
    }
