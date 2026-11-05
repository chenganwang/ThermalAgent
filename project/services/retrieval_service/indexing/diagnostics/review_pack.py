from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import os

from .schema import build_holdout_schema, build_review_ready_dataset, validate_review_ready_dataset


def _atomic_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def _summary(chunk_id: int, catalog: dict[int, dict[str, Any]]) -> str:
    item = catalog.get(int(chunk_id), {})
    preview = " ".join(str(item.get("text") or "").split())[:220]
    return (
        f"chunk={chunk_id}; doc={item.get('document_id')}; source={item.get('source_name')}; "
        f"page={item.get('page_start')}; section={item.get('section_title')}; preview={preview}"
    )


def render_review_markdown(
    dataset: dict[str, Any], catalog: dict[int, dict[str, Any]]
) -> str:
    lines = [
        "# Holdout-30 Human Validation Review Pack",
        "",
        "- human_validated: false",
        "- validation_status: pending",
        "- Codex conversion preserves annotations but does not replace human validation.",
    ]
    for case in dataset.get("cases") or []:
        lines.extend(
            [
                "",
                f"## {case.get('case_id')}",
                "",
                f"- Query: {case.get('query')}",
                f"- Category: {case.get('category')}",
                f"- Answerable (derived from original annotation): {case.get('answerable')}",
                f"- Expected documents: {case.get('expected_document_ids')}",
                f"- Expected chunks: {case.get('expected_chunk_ids')}",
                f"- Acceptable documents (current annotation): {case.get('acceptable_document_ids')}",
                f"- Acceptable chunks (current annotation): {case.get('acceptable_chunk_ids')}",
                f"- Must-not-return documents: {case.get('must_not_return_document_ids')}",
                f"- Must-not-return chunks (pending): {case.get('must_not_return_chunk_ids')}",
                f"- Validation status: {case.get('validation_status')}",
                "- Validation note (human):",
                "- Human error type (optional):",
                "- Required concepts (human):",
                "- Confusing concepts (human):",
                "",
                "### Source-grounded summaries",
            ]
        )
        ids = list(dict.fromkeys(
            list(case.get("expected_chunk_ids") or []) + list(case.get("acceptable_chunk_ids") or [])
        ))
        lines.extend(f"- {_summary(int(chunk_id), catalog)}" for chunk_id in ids)
    return "\n".join(lines) + "\n"


def write_review_pack(
    source_dataset: dict[str, Any],
    catalog: dict[int, dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    converted = build_review_ready_dataset(source_dataset)
    for case in converted["cases"]:
        acceptable_docs = {
            int(catalog[int(chunk_id)]["document_id"])
            for chunk_id in case.get("acceptable_chunk_ids") or []
            if int(chunk_id) in catalog and catalog[int(chunk_id)].get("document_id") is not None
        }
        case["acceptable_document_ids"] = sorted(
            acceptable_docs | {int(item) for item in case.get("expected_document_ids") or []}
        )
        case["human_validated"] = False
        case["validation_status"] = "pending"
    validation = validate_review_ready_dataset(converted)
    schema = build_holdout_schema()
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl = _atomic_text(
        output_dir / "holdout_30_review_ready.jsonl",
        "".join(
            json.dumps(case, ensure_ascii=False, default=str) + "\n"
            for case in converted["cases"]
        ),
    )
    markdown = _atomic_text(
        output_dir / "holdout_30_review_ready.md",
        render_review_markdown(converted, catalog),
    )
    schema_path = _atomic_text(
        output_dir / "holdout_schema.json",
        json.dumps(schema, ensure_ascii=False, indent=2),
    )
    source_blob = json.dumps(source_dataset, ensure_ascii=False, sort_keys=True).encode("utf-8")
    report = {
        "source_dataset_id": (source_dataset.get("metadata") or {}).get("dataset_id"),
        "source_case_count": len(source_dataset.get("cases") or []),
        "conversion_count": len(converted["cases"]),
        "source_dataset_sha256": sha256(source_blob).hexdigest(),
        "validation": validation,
        "human_validated_count": validation["human_validated_count"],
        "pending_count": validation["pending_count"],
        "annotation_loss_count": 0,
        "external_model_used": False,
        "human_validation_faked": False,
    }
    report_path = _atomic_text(
        output_dir / "holdout_conversion_report.json",
        json.dumps(report, ensure_ascii=False, indent=2),
    )
    return {
        "dataset": converted,
        "schema": schema,
        "validation": validation,
        "outputs": {
            "review_jsonl": str(jsonl.resolve()),
            "review_markdown": str(markdown.resolve()),
            "schema": str(schema_path.resolve()),
            "conversion_report": str(report_path.resolve()),
        },
    }
