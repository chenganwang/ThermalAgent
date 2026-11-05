from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.config import load_config  # noqa: E402
from services.retrieval_service.indexing.candidate_builder import (  # noqa: E402
    build_candidate_indexes,
    plan_candidate_build,
    utc_candidate_version,
)
from services.retrieval_service.indexing.index_manifest import (  # noqa: E402
    audit_old_index,
    build_candidate_chunk_manifest,
    snapshot_old_index,
)
from services.retrieval_service.indexing.index_validator import validate_candidate_index  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


def audit_markdown(audit: dict) -> str:
    return "\n".join(
        [
            "# Old Production Retrieval Index Audit",
            "",
            f"- version: {audit.get('index_version')}",
            f"- FAISS path: {audit.get('faiss', {}).get('path')}",
            f"- FAISS vectors: {audit.get('faiss', {}).get('ntotal')}",
            f"- FAISS dimension: {audit.get('faiss', {}).get('dimension')}",
            f"- FAISS metric type: {audit.get('faiss', {}).get('metric_type')}",
            f"- BM25 corpus: {audit.get('bm25', {}).get('corpus_count')}",
            f"- Database valid chunks: {audit.get('database', {}).get('valid_chunk_count')}",
            f"- Database/index difference: {audit.get('database_index_count_difference')}",
            f"- Mapping duplicates: {audit.get('old_mapping', {}).get('duplicate_chunk_ids')}",
            f"- Missing mappings: {audit.get('old_mapping', {}).get('missing_mapping_entries')}",
            "- Database written: false",
            "- Knowledge units included: false",
        ]
    ) + "\n"


def manifest_markdown(summary: dict) -> str:
    return "\n".join(["# Candidate Chunk Manifest", ""] + [f"- {key}: {value}" for key, value in summary.items()]) + "\n"


def build_markdown(payload: dict) -> str:
    return "\n".join(
        [
            "# Candidate Retrieval Index Build",
            "",
            f"- status: {payload.get('status')}",
            f"- version: {payload.get('version')}",
            f"- manifest count: {payload.get('manifest_count', payload.get('chunk_count'))}",
            f"- FAISS count: {payload.get('faiss_count')}",
            f"- BM25 count: {payload.get('bm25_count')}",
            f"- embedding model: {payload.get('embedding_model')}",
            f"- embedding dimension: {payload.get('embedding_dimension')}",
            f"- normalize: {payload.get('normalize')}",
            f"- BM25 k1/b: {payload.get('bm25_k1')}/{payload.get('bm25_b')}",
            "- Production files modified: false",
            "- Database written: false",
            "- Knowledge units included: false",
        ]
    ) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy-on-write FAISS/BM25 candidate builder")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--audit-snapshot", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--build", action="store_true")
    action.add_argument("--validate", action="store_true")
    parser.add_argument("--output-dir", default=str(ROOT / "runtime/index_upgrade"))
    parser.add_argument("--version", default=None)
    parser.add_argument("--batch", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(ROOT)
    output = Path(args.output_dir)
    candidate_root = output / "candidate"
    version = args.version or utc_candidate_version()

    if args.audit_snapshot:
        audit = audit_old_index(cfg)
        snapshot = snapshot_old_index(cfg, output / "snapshots", audit=audit)
        write_json(output / "old_index_audit.json", audit)
        (output / "old_index_audit.md").write_text(audit_markdown(audit), encoding="utf-8")
        write_json(output / "old_index_snapshot_manifest.json", snapshot)
        print(f"old_version={audit['index_version']} snapshot_verified={snapshot['snapshot_verified']}")
        return 0 if snapshot["snapshot_verified"] else 2

    manifest = build_candidate_chunk_manifest(cfg)
    manifest_path = output / "candidate_chunk_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as handle:
        for row in manifest["rows"]:
            handle.write(json.dumps({key: value for key, value in row.items() if key != "text"}, ensure_ascii=False, default=str) + "\n")
    write_json(output / "candidate_chunk_manifest_summary.json", manifest["summary"])
    (output / "candidate_chunk_manifest_summary.md").write_text(
        manifest_markdown(manifest["summary"]), encoding="utf-8"
    )

    if args.dry_run:
        plan = plan_candidate_build(cfg, candidate_root, version=version)
        write_json(output / "candidate_index_build_dry_run.json", plan)
        print(f"version={version} chunks={plan['chunk_count']} production_modified=false")
        return 0

    if args.build:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        build = build_candidate_indexes(cfg, candidate_root, version=version, batch_size=args.batch)
        write_json(output / "candidate_index_build_report.json", build)
        (output / "candidate_index_build_report.md").write_text(build_markdown(build), encoding="utf-8")
        if build.get("status") != "built":
            print(f"candidate build blocked: {build.get('blocking_reason')}")
            return 3
        write_json(candidate_root / "current_build.json", build)
        print(f"version={version} faiss={build['faiss_count']} bm25={build['bm25_count']}")
        return 0

    build = json.loads((candidate_root / "current_build.json").read_text(encoding="utf-8"))
    validation = validate_candidate_index(cfg, build)
    write_json(output / "candidate_index_validation.json", validation)
    print(
        f"passed={validation['passed']} faiss={validation.get('faiss_count')} "
        f"bm25={validation.get('bm25_count')} invalid={validation.get('invalid_chunk_mapping_count')}"
    )
    return 0 if validation["passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
