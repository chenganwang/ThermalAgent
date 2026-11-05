from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any


DEFAULT_SHADOW_REPORT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_retrieval_report.md"
DEFAULT_SHADOW_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_retrieval_report.json"


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(data: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    return output


def _hit_examples(result: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    hits = result.get("hits") or []
    examples: list[dict[str, Any]] = []
    for hit in hits[:limit]:
        if not isinstance(hit, dict):
            continue
        examples.append(
            {
                "unit_code": hit.get("unit_code"),
                "dedup_key": hit.get("dedup_key"),
                "unit_type": hit.get("unit_type"),
                "canonical_name": hit.get("canonical_name"),
                "document_id": hit.get("document_id"),
                "source_chunk_id": hit.get("source_chunk_id"),
                "provenance_status": hit.get("provenance_status"),
                "match_reason": hit.get("match_reason"),
            }
        )
    return examples


def build_shadow_report_payload(results: list[dict[str, Any]], *, query_specs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    normalized = [dict(item) for item in results or [] if isinstance(item, dict)]
    query_count = len(normalized)
    hit_query_count = sum(1 for item in normalized if int(item.get("hit_count") or 0) > 0)
    miss_count = query_count - hit_query_count
    counts_by_unit_type: Counter[str] = Counter()
    provenance_ready_count = 0
    total_returned_hit_count = 0
    examples: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, result in enumerate(normalized):
        hits = [hit for hit in (result.get("hits") or []) if isinstance(hit, dict)]
        total_returned_hit_count += len(hits)
        for hit in hits:
            counts_by_unit_type[str(hit.get("unit_type") or "unknown")] += 1
            if str(hit.get("provenance_status") or "").lower() == "ready":
                provenance_ready_count += 1
        if result.get("status") == "error":
            errors.append(
                {
                    "query": result.get("query"),
                    "error_type": result.get("error_type"),
                    "error": result.get("error"),
                }
            )
        if len(examples) < 10:
            spec = query_specs[index] if query_specs and index < len(query_specs) else {}
            examples.append(
                {
                    "query": result.get("query") or spec.get("query"),
                    "unit_type_filter": result.get("unit_type_filter") or spec.get("unit_types") or [],
                    "status": result.get("status"),
                    "hit_count": int(result.get("hit_count") or 0),
                    "hits": _hit_examples(result),
                }
            )

    status = "ok" if not errors else "error"
    next_steps = (
        [
            "Review hit quality against engineering questions before deciding whether Phase 2E should broaden evaluation.",
            "Keep the adapter optional and disabled in the agent main path until a separate integration decision is made.",
        ]
        if status == "ok"
        else [
            "Restore read-only database connectivity or fix the knowledge_units schema, then rerun shadow retrieval.",
            "Do not wire knowledge_units into the default agent path based on this error report.",
        ]
    )

    return {
        "status": status,
        "query_count": query_count,
        "hit_count": hit_query_count,
        "miss_count": miss_count,
        "total_returned_hit_count": total_returned_hit_count,
        "counts_by_unit_type": dict(sorted(counts_by_unit_type.items())),
        "provenance_ready_count": provenance_ready_count,
        "examples": examples,
        "errors": errors,
        "database_written": False,
        "readonly": True,
        "default_agent_dependency": False,
        "next_steps": next_steps,
    }


def write_shadow_report_json(data: dict[str, Any], path: str | Path = DEFAULT_SHADOW_REPORT_JSON) -> Path:
    return _write_json(data, path)


def write_shadow_report_markdown(data: dict[str, Any], path: str | Path = DEFAULT_SHADOW_REPORT_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Knowledge Unit Shadow Retrieval Report",
        "",
        "## Summary",
        "",
        f"- status: {data.get('status')}",
        f"- query_count: {data.get('query_count', 0)}",
        f"- hit_count: {data.get('hit_count', 0)}",
        f"- miss_count: {data.get('miss_count', 0)}",
        f"- total_returned_hit_count: {data.get('total_returned_hit_count', 0)}",
        f"- counts_by_unit_type: {json.dumps(data.get('counts_by_unit_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- provenance_ready_count: {data.get('provenance_ready_count', 0)}",
        f"- database_written: {str(bool(data.get('database_written'))).lower()}",
        f"- readonly: {str(bool(data.get('readonly'))).lower()}",
        f"- default_agent_dependency: {str(bool(data.get('default_agent_dependency'))).lower()}",
        "",
        "## Examples",
        "",
    ]
    examples = data.get("examples") or []
    if examples:
        for item in examples[:10]:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Errors", ""])
    errors = data.get("errors") or []
    if errors:
        for item in errors:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Next Steps", ""])
    for step in data.get("next_steps") or []:
        lines.append(f"- {step}")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This report is generated by the optional knowledge_units shadow retrieval adapter.",
            "- The adapter executes SELECT-only queries when explicitly enabled by the shadow script.",
            "- No INSERT, UPDATE, DELETE, ALTER, DROP, OCR, PDF ingest, index rebuild, model call, external API call, or retrieval_service main-chain change is performed.",
            "- The default agent and /agent/answer contract do not depend on knowledge_units.",
            "- Database credentials are not printed or written to this report.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_shadow_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_SHADOW_REPORT_MD,
    report_json: str | Path = DEFAULT_SHADOW_REPORT_JSON,
) -> dict[str, str]:
    report_json_path = write_shadow_report_json(data, report_json)
    report_md_path = write_shadow_report_markdown(data, report_md)
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}


__all__ = [
    "DEFAULT_SHADOW_REPORT_JSON",
    "DEFAULT_SHADOW_REPORT_MD",
    "build_shadow_report_payload",
    "write_shadow_outputs",
    "write_shadow_report_json",
    "write_shadow_report_markdown",
]
