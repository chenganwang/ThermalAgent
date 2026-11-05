from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_RUNS_DIR = Path("runtime") / "knowledge_unit_candidates" / "runs"
REVIEWED_FILE_NAME = "sample_knowledge_unit_review_sheet_reviewed.jsonl"
CANDIDATES_FILE_NAME = "sample_knowledge_unit_candidates.jsonl"
SAMPLE_CHUNKS_FILE_NAME = "sample_chunks.json"

DOCUMENT_ID_FIELDS = ("document_id", "doc_id", "source_doc_id", "source_document_id")
CHUNK_ID_FIELDS = ("source_chunk_id", "chunk_id")
SAMPLE_CHUNK_ID_FIELDS = ("source_chunk_id", "chunk_id", "id")
ASSET_ID_FIELDS = ("source_asset_id", "asset_id", "source_file", "file_path")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _source(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("source")
    return value if isinstance(value, dict) else {}


def _properties(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("properties")
    return value if isinstance(value, dict) else {}


def _norm_text(value: Any) -> str:
    text = _text(value).lower()
    return re.sub(r"\s+", " ", text)


def _preview(record: dict[str, Any]) -> str:
    source = _source(record)
    return _text(record.get("source_text_preview") or source.get("source_text_preview"))


def _candidate_id(record: dict[str, Any]) -> str:
    return _text(record.get("candidate_id") or record.get("id"))


def _dedup_key(record: dict[str, Any]) -> str:
    return _text(record.get("dedup_key"))


def _first_present(record: dict[str, Any], field_names: tuple[str, ...]) -> Any:
    source = _source(record)
    properties = _properties(record)
    for container in (record, source, properties):
        for name in field_names:
            value = container.get(name)
            if _present(value):
                return value
    return None


def _run_dirs(runs_dir: str | Path) -> list[Path]:
    root = Path(runs_dir)
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not path.exists():
        return records, [f"missing_file:{path}"]
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                value = json.loads(raw)
            except Exception as exc:
                warnings.append(f"invalid_json_line:{path}:{line_no}:{type(exc).__name__}")
                continue
            if isinstance(value, dict):
                records.append(value)
            else:
                warnings.append(f"non_object_line:{path}:{line_no}")
    return records, warnings


def _load_json_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], [f"missing_file:{path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return [], [f"invalid_json:{path}:{type(exc).__name__}"]

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("chunks") or data.get("items") or data.get("data") or []
    else:
        rows = []
    records = [row for row in rows if isinstance(row, dict)]
    skipped = len(rows) - len(records) if isinstance(rows, list) else 0
    warnings = [f"non_object_rows:{path}:{skipped}"] if skipped else []
    return records, warnings


def _index_records(records: list[dict[str, Any]], run_name: str) -> dict[str, Any]:
    by_candidate_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_dedup_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_preview: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_dedup_preview: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    indexed: list[dict[str, Any]] = []

    for record in records:
        item = dict(record)
        item.setdefault("source_run_name", run_name)
        indexed.append(item)
        candidate_id = _candidate_id(item)
        dedup_key = _dedup_key(item)
        preview_key = _norm_text(_preview(item))
        if candidate_id:
            by_candidate_id[candidate_id].append(item)
        if dedup_key:
            by_dedup_key[dedup_key].append(item)
        if preview_key:
            by_preview[preview_key].append(item)
        if dedup_key and preview_key:
            by_dedup_preview[(dedup_key, preview_key)].append(item)

    return {
        "records": indexed,
        "by_candidate_id": dict(by_candidate_id),
        "by_dedup_key": dict(by_dedup_key),
        "by_preview": dict(by_preview),
        "by_dedup_preview": dict(by_dedup_preview),
    }


def load_run_review_records(runs_dir: str) -> dict:
    combined: dict[str, Any] = {
        "records": [],
        "by_candidate_id": defaultdict(list),
        "by_dedup_key": defaultdict(list),
        "by_preview": defaultdict(list),
        "by_dedup_preview": defaultdict(list),
        "by_run": {},
        "warnings": [],
    }
    for run_dir in _run_dirs(runs_dir):
        path = run_dir / REVIEWED_FILE_NAME
        records, warnings = _load_jsonl(path)
        indexed = _index_records(records, run_dir.name)
        combined["records"].extend(indexed["records"])
        combined["warnings"].extend(warnings)
        combined["by_run"][run_dir.name] = indexed["records"]
        for key in ("by_candidate_id", "by_dedup_key", "by_preview", "by_dedup_preview"):
            for item_key, values in indexed[key].items():
                combined[key][item_key].extend(values)

    for key in ("by_candidate_id", "by_dedup_key", "by_preview", "by_dedup_preview"):
        combined[key] = dict(combined[key])
    return combined


def load_run_candidate_records(runs_dir: str) -> dict:
    combined: dict[str, Any] = {
        "records": [],
        "by_candidate_id": defaultdict(list),
        "by_dedup_key": defaultdict(list),
        "by_preview": defaultdict(list),
        "by_dedup_preview": defaultdict(list),
        "by_run": {},
        "warnings": [],
    }
    for run_dir in _run_dirs(runs_dir):
        path = run_dir / CANDIDATES_FILE_NAME
        records, warnings = _load_jsonl(path)
        indexed = _index_records(records, run_dir.name)
        combined["records"].extend(indexed["records"])
        combined["warnings"].extend(warnings)
        combined["by_run"][run_dir.name] = indexed["records"]
        for key in ("by_candidate_id", "by_dedup_key", "by_preview", "by_dedup_preview"):
            for item_key, values in indexed[key].items():
                combined[key][item_key].extend(values)

    for key in ("by_candidate_id", "by_dedup_key", "by_preview", "by_dedup_preview"):
        combined[key] = dict(combined[key])
    return combined


def load_run_sample_chunks(runs_dir: str) -> dict:
    combined: dict[str, Any] = {
        "records": [],
        "by_run": {},
        "by_chunk_id": defaultdict(list),
        "warnings": [],
    }
    for run_dir in _run_dirs(runs_dir):
        path = run_dir / SAMPLE_CHUNKS_FILE_NAME
        records, warnings = _load_json_records(path)
        indexed: list[dict[str, Any]] = []
        for record in records:
            item = dict(record)
            item.setdefault("source_run_name", run_dir.name)
            indexed.append(item)
            chunk_id = _first_present(item, SAMPLE_CHUNK_ID_FIELDS)
            if _present(chunk_id):
                combined["by_chunk_id"][f"{run_dir.name}:{chunk_id}"].append(item)
        combined["records"].extend(indexed)
        combined["by_run"][run_dir.name] = indexed
        combined["warnings"].extend(warnings)
    combined["by_chunk_id"] = dict(combined["by_chunk_id"])
    return combined


def _best_record(records: list[dict[str, Any]], run_name: str, preview: str) -> dict[str, Any] | None:
    if not records:
        return None
    preview_key = _norm_text(preview)
    same_run = [record for record in records if _text(record.get("source_run_name")) == run_name] if run_name else []
    if preview_key:
        for record in same_run or records:
            if _norm_text(_preview(record)) == preview_key:
                return record
    if same_run:
        return same_run[0]
    return records[0]


def _find_index_match(candidate: dict[str, Any], index: dict[str, Any]) -> dict[str, Any] | None:
    candidate_id = _candidate_id(candidate)
    dedup_key = _dedup_key(candidate)
    preview = _preview(candidate)
    preview_key = _norm_text(preview)
    run_name = _text(candidate.get("source_run_name"))

    candidates: list[dict[str, Any]] = []
    if candidate_id:
        candidates.extend(index.get("by_candidate_id", {}).get(candidate_id, []))
    if dedup_key and preview_key:
        candidates.extend(index.get("by_dedup_preview", {}).get((dedup_key, preview_key), []))
    if not candidates and dedup_key:
        candidates.extend(index.get("by_dedup_key", {}).get(dedup_key, []))
    if not candidates and preview_key:
        candidates.extend(index.get("by_preview", {}).get(preview_key, []))

    # Preserve first-seen order while removing object duplicates.
    unique: list[dict[str, Any]] = []
    seen: set[int] = set()
    for record in candidates:
        marker = id(record)
        if marker not in seen:
            seen.add(marker)
            unique.append(record)
    return _best_record(unique, run_name, preview)


def _chunk_text(chunk: dict[str, Any]) -> str:
    for name in ("text", "content", "chunk_text", "source_text_preview"):
        text = _text(chunk.get(name))
        if text:
            return text
    return ""


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {token for token in re.split(r"[^0-9a-zA-Z_]+", left.lower()) if len(token) > 2}
    right_tokens = {token for token in re.split(r"[^0-9a-zA-Z_]+", right.lower()) if len(token) > 2}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))


def _find_chunk_match(candidate: dict[str, Any], chunks_index: dict[str, Any]) -> dict[str, Any] | None:
    run_name = _text(candidate.get("source_run_name"))
    chunks = chunks_index.get("by_run", {}).get(run_name) if run_name else None
    if not chunks:
        chunks = chunks_index.get("records") or []

    preview = _norm_text(_preview(candidate))
    content = _norm_text(candidate.get("content"))
    for chunk in chunks:
        chunk_text = _norm_text(_chunk_text(chunk))
        if not chunk_text:
            continue
        if preview and (preview in chunk_text or chunk_text.startswith(preview[:120])):
            return chunk
        if content and content in chunk_text:
            return chunk
        if preview and _token_overlap(preview, chunk_text) >= 0.72:
            return chunk
    return None


def _apply_fields(
    target: dict[str, Any],
    record: dict[str, Any],
    method: str,
    methods: list[str],
    *,
    chunk_id_fields: tuple[str, ...] = CHUNK_ID_FIELDS,
) -> None:
    document_id = _first_present(record, DOCUMENT_ID_FIELDS)
    chunk_id = _first_present(record, chunk_id_fields)
    asset_id = _first_present(record, ASSET_ID_FIELDS)
    run_name = _text(record.get("source_run_name"))

    changed = False
    if not _present(target.get("document_id")) and _present(document_id):
        target["document_id"] = document_id
        changed = True
    if not _present(target.get("source_chunk_id")) and _present(chunk_id):
        target["source_chunk_id"] = chunk_id
        changed = True
    if not _present(target.get("source_asset_id")) and _present(asset_id):
        target["source_asset_id"] = asset_id
        changed = True
    if not _present(target.get("source_run_name")) and run_name:
        target["source_run_name"] = run_name
        changed = True

    if changed and method not in methods:
        methods.append(method)


def _stable_source_hash(candidate: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "candidate_id": _candidate_id(candidate),
            "dedup_key": _dedup_key(candidate),
            "source_text_preview": _preview(candidate),
            "source_run_name": candidate.get("source_run_name"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def backfill_candidate_provenance(candidate: dict, indexes: dict) -> dict:
    enhanced = dict(candidate or {}) if isinstance(candidate, dict) else {}
    methods: list[str] = []

    _apply_fields(enhanced, enhanced, "candidate_fields", methods)

    review_match = _find_index_match(enhanced, indexes.get("review_records") or {})
    if review_match:
        _apply_fields(enhanced, review_match, "run_review_record", methods)

    candidate_match = _find_index_match(enhanced, indexes.get("candidate_records") or {})
    if candidate_match:
        _apply_fields(enhanced, candidate_match, "run_candidate_record", methods)

    if not (_present(enhanced.get("document_id")) and _present(enhanced.get("source_chunk_id"))):
        chunk_match = _find_chunk_match(enhanced, indexes.get("sample_chunks") or {})
        if chunk_match:
            _apply_fields(enhanced, chunk_match, "sample_chunk_text_match", methods, chunk_id_fields=SAMPLE_CHUNK_ID_FIELDS)

    warnings: list[str] = []
    if not _present(enhanced.get("document_id")):
        warnings.append("missing_document_id")
    if not _present(enhanced.get("source_chunk_id")):
        warnings.append("missing_source_chunk_id")
    if not methods:
        warnings.append("no_structured_provenance_match")

    has_document = _present(enhanced.get("document_id"))
    has_chunk = _present(enhanced.get("source_chunk_id"))
    has_support = any(
        _present(enhanced.get(name))
        for name in ("source_asset_id", "source_run_name", "source_text_preview", "reviewed_file")
    )
    if has_document and has_chunk:
        status = "ready"
    elif has_document or has_chunk or has_support:
        status = "partial"
        if not (has_document and has_chunk):
            warnings.append("partial_provenance")
    else:
        status = "missing"
        warnings.append("missing_provenance")

    enhanced["provenance_status"] = status
    enhanced["provenance_warnings"] = sorted(set(warnings))
    enhanced["provenance_backfill_method"] = "+".join(methods) if methods else "none"
    enhanced.setdefault("source_provenance_hash", _stable_source_hash(enhanced))
    return enhanced


def backfill_candidates_provenance(candidates: list[dict], runs_dir: str) -> dict:
    indexes = {
        "review_records": load_run_review_records(runs_dir),
        "candidate_records": load_run_candidate_records(runs_dir),
        "sample_chunks": load_run_sample_chunks(runs_dir),
    }
    enhanced = [backfill_candidate_provenance(candidate, indexes) for candidate in candidates or [] if isinstance(candidate, dict)]
    status_counts = Counter(candidate.get("provenance_status") or "missing" for candidate in enhanced)
    warning_counts: Counter[str] = Counter()
    for candidate in enhanced:
        for warning in candidate.get("provenance_warnings") or []:
            warning_counts[str(warning)] += 1

    return {
        "status": "ok",
        "runs_dir": str(Path(runs_dir)),
        "candidates": enhanced,
        "total_candidates": len(enhanced),
        "provenance_ready_count": int(status_counts.get("ready", 0)),
        "provenance_partial_count": int(status_counts.get("partial", 0)),
        "provenance_missing_count": int(status_counts.get("missing", 0)),
        "warnings_by_type": dict(sorted(warning_counts.items())),
        "index_summary": {
            "review_records_count": len(indexes["review_records"].get("records") or []),
            "candidate_records_count": len(indexes["candidate_records"].get("records") or []),
            "sample_chunks_count": len(indexes["sample_chunks"].get("records") or []),
            "review_warnings": indexes["review_records"].get("warnings") or [],
            "candidate_warnings": indexes["candidate_records"].get("warnings") or [],
            "sample_chunk_warnings": indexes["sample_chunks"].get("warnings") or [],
        },
        "database_written": False,
    }
