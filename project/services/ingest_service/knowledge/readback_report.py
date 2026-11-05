from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_READBACK_REPORT_MD = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_readback_report.md"
DEFAULT_READBACK_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_readback_report.json"


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(data: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    return output


def build_readback_report_payload(
    *,
    input_path: str | Path,
    readback_result: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(comparison)
    readback_status = str(readback_result.get("status") or "unknown")
    readback_errors = list(readback_result.get("errors") or [])
    if readback_status != "ok":
        payload["status"] = "error"
        payload["can_enter_phase2d"] = False
        payload["next_steps"] = [
            "Restore read-only database connectivity or fix the knowledge_units schema, then rerun readback.",
            "Do not enter Phase 2D until readback status is ok and field mismatches are zero.",
        ]
    payload.update(
        {
            "input_path": str(Path(input_path)),
            "readback_status": readback_status,
            "readback_error_type": readback_result.get("error_type"),
            "readback_errors": readback_errors,
            "target_table": readback_result.get("target_table", "knowledge_units"),
            "schema_fields": readback_result.get("schema_fields") or [],
            "query_mode": readback_result.get("query_mode"),
            "db_connection_opened": bool(readback_result.get("db_connection_opened")),
            "database_written": False,
            "readonly": True,
        }
    )
    payload.setdefault("expected_count", int(readback_result.get("expected_count") or 0))
    payload.setdefault("found_count", 0)
    payload.setdefault("missing_count", payload.get("expected_count", 0))
    payload.setdefault("duplicate_count", 0)
    payload.setdefault("field_match_count", 0)
    payload.setdefault("field_mismatch_count", 0)
    payload.setdefault("counts_by_unit_type", {})
    payload.setdefault("missing_dedup_keys", [])
    payload.setdefault("mismatched_examples", [])
    payload.setdefault("readback_examples", [])
    payload.setdefault("next_steps", ["Review this readback report before Phase 2D."])
    return payload


def write_readback_report_json(data: dict[str, Any], path: str | Path = DEFAULT_READBACK_REPORT_JSON) -> Path:
    return _write_json(data, path)


def write_readback_report_markdown(data: dict[str, Any], path: str | Path = DEFAULT_READBACK_REPORT_MD) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Knowledge Unit Readback Report",
        "",
        "## Summary",
        "",
        f"- status: {data.get('status')}",
        f"- readback_status: {data.get('readback_status')}",
        f"- input_path: {data.get('input_path')}",
        f"- target_table: {data.get('target_table')}",
        f"- query_mode: {data.get('query_mode')}",
        f"- expected_count: {data.get('expected_count', 0)}",
        f"- found_count: {data.get('found_count', 0)}",
        f"- missing_count: {data.get('missing_count', 0)}",
        f"- duplicate_count: {data.get('duplicate_count', 0)}",
        f"- field_match_count: {data.get('field_match_count', 0)}",
        f"- field_mismatch_count: {data.get('field_mismatch_count', 0)}",
        f"- counts_by_unit_type: {json.dumps(data.get('counts_by_unit_type') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- database_written: {str(bool(data.get('database_written'))).lower()}",
        f"- readonly: {str(bool(data.get('readonly'))).lower()}",
        f"- db_connection_opened: {str(bool(data.get('db_connection_opened'))).lower()}",
        f"- can_enter_phase2d: {str(bool(data.get('can_enter_phase2d'))).lower()}",
        "",
        "## Missing Dedup Keys",
        "",
    ]
    missing = data.get("missing_dedup_keys") or []
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- none")

    lines.extend(["", "## Mismatched Examples", ""])
    mismatches = data.get("mismatched_examples") or []
    if mismatches:
        for item in mismatches[:10]:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Readback Examples", ""])
    examples = data.get("readback_examples") or []
    if examples:
        for item in examples[:10]:
            lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True, default=_json_default)}")
    else:
        lines.append("- none")

    lines.extend(["", "## Errors", ""])
    errors = data.get("readback_errors") or []
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
            "- This report is generated from SELECT-only readback.",
            "- No INSERT, UPDATE, DELETE, ALTER, DROP, OCR, PDF ingest, index rebuild, model call, external API call, or retrieval_service main-chain change is performed.",
            "- Database credentials are not printed or written to this report.",
        ]
    )
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_readback_outputs(
    data: dict[str, Any],
    *,
    report_md: str | Path = DEFAULT_READBACK_REPORT_MD,
    report_json: str | Path = DEFAULT_READBACK_REPORT_JSON,
) -> dict[str, str]:
    report_json_path = write_readback_report_json(data, report_json)
    report_md_path = write_readback_report_markdown(data, report_md)
    return {"report_md": str(report_md_path), "report_json": str(report_json_path)}
