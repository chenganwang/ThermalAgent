from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import os
import re


SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
TEMPORARY_SUFFIXES = {".tmp", ".bak"}

HIGH_RELEVANCE_TERMS = {
    "liquid cooling", "data center", "cold plate", "coolant", "cdu", "manifold",
    "chip cooling", "processor thermal", "thermal management", "pressure drop", "pump",
    "液冷", "冷板", "冷却液", "数据中心", "芯片散热", "压降", "热阻", "泵", "微通道",
}
MEDIUM_RELEVANCE_TERMS = {
    "heat transfer", "thermal", "cooling", "reynolds", "flow channel", "heat exchanger",
    "传热", "换热", "散热", "流道", "雷诺数", "热管理",
}
NOVELTY_TERMS = {
    "egw", "pgw", "glycol", "pressure drop", "pump", "manifold", "parallel", "fault",
    "leak", "blockage", "thermal resistance", "压降", "泵", "并联", "堵塞", "泄漏", "热阻",
}


def normalize_absolute_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def is_path_within(path: str | Path, root: str | Path) -> bool:
    candidate = Path(path).resolve()
    boundary = Path(root).resolve()
    try:
        candidate.relative_to(boundary)
        return True
    except ValueError:
        return False


def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _existing_indexes(existing_documents: Iterable[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
    paths: set[str] = set()
    hashes: set[str] = set()
    titles: set[str] = set()
    for document in existing_documents or []:
        if not isinstance(document, dict):
            continue
        for field in ("source", "local_path", "file_path"):
            value = document.get(field)
            if value:
                try:
                    paths.add(normalize_absolute_path(value))
                except Exception:
                    pass
        value = str(document.get("sha256") or document.get("source_hash") or "").strip().lower()
        if value:
            hashes.add(value)
        title = str(document.get("title") or "").strip().casefold()
        if title:
            titles.add(title)
    return paths, hashes, titles


def _basic_exclusion(path: Path) -> str | None:
    if path.name.startswith("~$"):
        return "temporary_office_file"
    if path.suffix.lower() in TEMPORARY_SUFFIXES:
        return "temporary_or_backup_file"
    if any(part.startswith(".") for part in path.parts):
        return "hidden_file"
    lower_parts = {part.casefold() for part in path.parts}
    if lower_parts.intersection({"runtime", "extraction_output", "extracted", "__pycache__"}):
        return "generated_output"
    if path.suffix.lower() in {".sql", ".dump"}:
        return "database_dump"
    return None


def build_external_source_inventory(
    *,
    source_root: str | Path,
    exclude_root: str | Path,
    existing_documents: Iterable[dict[str, Any]] = (),
    inspect_content: bool = False,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    excluded_boundary = Path(exclude_root).resolve()
    existing_paths, existing_hashes, existing_titles = _existing_indexes(existing_documents)
    records: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}

    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: normalize_absolute_path(item)):
        stat = path.stat()
        normalized = normalize_absolute_path(path)
        digest = sha256_file(path)
        hard_excluded = is_path_within(path, excluded_boundary)
        exclusion_reason = "excluded_root" if hard_excluded else _basic_exclusion(path)
        extension = path.suffix.lower()
        parser_supported = extension in SUPPORTED_EXTENSIONS
        duplicate_by_hash = digest in existing_hashes or digest in seen_hashes
        duplicate_by_path = normalized in existing_paths
        duplicate_by_title = path.name.casefold() in existing_titles
        already_ingested = duplicate_by_hash or duplicate_by_path

        if not exclusion_reason and not parser_supported:
            exclusion_reason = "unsupported_format"
        if not exclusion_reason and duplicate_by_hash:
            exclusion_reason = "duplicate_hash"
        if not exclusion_reason and duplicate_by_path:
            exclusion_reason = "duplicate_path"

        if digest not in seen_hashes:
            seen_hashes[digest] = normalized

        record = {
            "absolute_path": str(path),
            "normalized_path": normalized,
            "relative_path": str(path.relative_to(root)),
            "filename": path.name,
            "extension": extension,
            "size_bytes": int(stat.st_size),
            "modified_time": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "sha256": digest,
            "parser_supported": parser_supported,
            "text_extractable": None if inspect_content else parser_supported,
            "already_ingested": already_ingested,
            "duplicate_by_hash": duplicate_by_hash,
            "duplicate_by_path": duplicate_by_path,
            "duplicate_by_title": duplicate_by_title,
            "excluded": bool(exclusion_reason),
            "exclusion_reason": exclusion_reason,
            "relevance_score": 0.0,
            "quality_score": 0.0,
            "novelty_score": 0.0,
            "provenance_score": 0.0,
            "final_score": 0.0,
            "selection_status": "excluded" if exclusion_reason else "candidate",
            "selection_reason": exclusion_reason or "pending_content_inspection",
        }
        records.append(record)

    summary_counter = Counter(str(item.get("exclusion_reason") or "candidate") for item in records)
    summary = {
        "scanned_file_count": len(records),
        "excluded_root_file_count": int(summary_counter.get("excluded_root", 0)),
        "already_ingested_file_count": sum(1 for item in records if item["already_ingested"]),
        "hash_duplicate_file_count": sum(1 for item in records if item["duplicate_by_hash"]),
        "unsupported_format_count": int(summary_counter.get("unsupported_format", 0)),
        "ocr_required_count": 0,
        "valid_candidate_count": sum(1 for item in records if not item["excluded"]),
        "selected_file_count": 0,
        "excluded_backbone_selected_count": 0,
    }
    return {
        "source_root": str(root),
        "exclude_root": str(excluded_boundary),
        "files": records,
        "summary": summary,
    }


def select_external_sources(
    inventory: list[dict[str, Any]],
    *,
    max_files: int = 6,
    min_score: float = 0.45,
) -> list[dict[str, Any]]:
    limit = max(0, min(int(max_files), 8))
    eligible = []
    for raw in inventory or []:
        item = dict(raw)
        if item.get("excluded"):
            continue
        if not item.get("parser_supported") or not item.get("text_extractable"):
            continue
        if item.get("already_ingested") or item.get("duplicate_by_hash"):
            continue
        if float(item.get("final_score") or 0.0) < float(min_score):
            continue
        eligible.append(item)
    eligible.sort(key=lambda item: (-float(item.get("final_score") or 0.0), str(item.get("filename") or "").casefold()))
    selected = eligible[:limit]
    for item in selected:
        item["selection_status"] = "selected"
        item["selection_reason"] = "highest_value_parseable_nonduplicate_source"
    return selected


def build_external_ingestion_dry_run(
    *,
    selected_files: list[dict[str, Any]],
    parsed_documents: dict[str, dict[str, Any]],
    accepted_candidates: list[dict[str, Any]],
    existing_document_hashes: set[str],
    existing_unit_keys: set[str],
) -> dict[str, Any]:
    blocking_errors: list[str] = []
    planned_documents = 0
    planned_chunks = 0
    skipped_existing_documents = 0

    for item in selected_files or []:
        if item.get("excluded") or item.get("exclusion_reason") == "excluded_root":
            blocking_errors.append(f"excluded_source_selected:{item.get('filename') or item.get('absolute_path')}")
            continue
        digest = str(item.get("sha256") or "").lower()
        if not digest:
            blocking_errors.append(f"missing_sha256:{item.get('filename') or 'unknown'}")
            continue
        if digest in existing_document_hashes:
            skipped_existing_documents += 1
            continue
        parsed = parsed_documents.get(digest) or {}
        if not parsed.get("quality_passed"):
            continue
        planned_documents += 1
        planned_chunks += int(parsed.get("chunk_count") or 0)

    new_units = []
    skipped_duplicate_units = 0
    seen_unit_keys = set(existing_unit_keys or set())
    for candidate in accepted_candidates or []:
        key = str(candidate.get("dedup_key") or "").strip()
        if not key:
            blocking_errors.append("accepted_candidate_missing_dedup_key")
            continue
        if candidate.get("review_status") != "accepted":
            blocking_errors.append(f"nonaccepted_candidate_in_write_plan:{key}")
            continue
        if key in seen_unit_keys:
            skipped_duplicate_units += 1
            continue
        seen_unit_keys.add(key)
        new_units.append(candidate)

    return {
        "status": "blocked" if blocking_errors else "ready",
        "blocking_errors": blocking_errors,
        "selected_file_count": len(selected_files or []),
        "planned_source_asset_inserts": planned_documents,
        "planned_document_inserts": planned_documents,
        "planned_chunk_inserts": planned_chunks,
        "planned_knowledge_unit_inserts": len(new_units),
        "skipped_existing_documents": skipped_existing_documents,
        "skipped_duplicate_units": skipped_duplicate_units,
        "new_unit_keys": [str(item.get("dedup_key")) for item in new_units],
    }


def _source_ready(source: dict[str, Any]) -> bool:
    return bool(
        source.get("document_id")
        and source.get("chunk_id")
        and (source.get("page_no") is not None or str(source.get("section_title") or "").strip())
        and str(source.get("source_text_preview") or "").strip()
    )


def _candidate_semantic_issues(candidate: dict[str, Any]) -> tuple[list[str], list[str]]:
    unit_type = str(candidate.get("unit_type") or "").strip()
    canonical = str(candidate.get("canonical_name") or "").strip()
    content = str(candidate.get("content") or "").strip()
    properties = candidate.get("properties") if isinstance(candidate.get("properties"), dict) else {}
    lower = content.casefold()
    hard: list[str] = []
    review: list[str] = []

    if len(content) < 20:
        review.append("content_too_short_for_standalone_unit")
    if len(content) > 600 or len(canonical) > 160 or len(canonical.split()) > 20:
        hard.append("candidate_not_atomic")
    if any(
        marker in lower
        for marker in (
            "revision history", "do not scale drawing", "drawing number", "sheet 1 of 1",
            "copyright", "all rights reserved", "future work will", "rolled part number",
            "tooling release", "unless otherwise specified",
        )
    ):
        hard.append("document_noise_or_revision_content")
    alnum = re.findall(r"[0-9a-z\u4e00-\u9fff]", lower)
    if content and len(alnum) / max(1, len(content)) < 0.35:
        hard.append("low_semantic_character_ratio")

    if unit_type == "thermal_path":
        nodes = properties.get("nodes") or properties.get("path")
        nodes = nodes if isinstance(nodes, list) else []
        known = {
            "chip", "processor", "tim", "cold plate", "cold_plate", "coolant", "cdu", "pump",
            "heat exchanger", "it loop", "facility loop", "ambient", "atmosphere", "heat sink",
            "server", "manifold", "facility water", "secondary loop", "primary loop",
        }
        normalized_nodes = [str(node).strip().casefold().replace("_", " ") for node in nodes]
        if "->" not in content or not 2 <= len(nodes) <= 8:
            review.append("thermal_path_nodes_incomplete")
        if any(len(node) > 60 or len(node.split()) > 8 for node in normalized_nodes):
            hard.append("thermal_path_node_not_atomic")
        if normalized_nodes and not all(node in known for node in normalized_nodes):
            review.append("thermal_path_domain_nodes_unclear")
        if len(content) > 360:
            hard.append("thermal_path_content_too_broad")
    elif unit_type == "formula":
        expression = properties.get("expression") or properties.get("formula") or (content if "=" in content else None)
        if not expression:
            review.append("formula_expression_missing")
        if not properties.get("variables"):
            review.append("formula_variables_incomplete")
        if not properties.get("units"):
            review.append("formula_units_incomplete")
    elif unit_type == "parameter":
        has_value = any(properties.get(name) not in (None, "", [], {}) for name in ("value", "values", "range"))
        has_unit = any(properties.get(name) not in (None, "", [], {}) for name in ("unit", "units"))
        if not has_value and not re.search(r"\d", content):
            review.append("parameter_value_missing")
        if not has_unit and not re.search(r"(?:\bpa\b|\bkpa\b|l/min|kg/s|w/[mk]|%|\u00b0c|\bk\b)", lower):
            review.append("parameter_unit_missing")
    elif unit_type in {"concept", "component"}:
        if len(content) > 360:
            hard.append("definition_not_atomic")
    elif unit_type == "fault_case":
        causes = properties.get("possible_causes") or properties.get("causes")
        if not causes and not re.search(r"cause|due to|leak|block|failure|导致|原因|泄漏|堵塞", lower):
            review.append("fault_cause_evidence_incomplete")
    return hard, review


def gate_external_knowledge_candidates(
    candidates: list[dict[str, Any]],
    *,
    existing_dedup_keys: set[str],
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen = set(existing_dedup_keys or set())

    for raw in candidates or []:
        candidate = dict(raw)
        source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
        key = str(candidate.get("dedup_key") or "").strip()
        confidence = float(candidate.get("confidence") or 0.0)
        quality = float(candidate.get("quality_score") or 0.0)
        reasons: list[str] = []
        if not key:
            reasons.append("missing_dedup_key")
        if key in seen:
            reasons.append("duplicate")
        if not str(candidate.get("content") or "").strip():
            reasons.append("missing_content")
        if not _source_ready(source):
            reasons.append("provenance_incomplete")
        semantic_hard, semantic_review = _candidate_semantic_issues(candidate)
        reasons.extend(semantic_hard)

        if reasons:
            candidate["review_status"] = "rejected"
            candidate["gate_reasons"] = reasons
            rejected.append(candidate)
            continue

        seen.add(key)
        if confidence >= 0.80 and quality >= 0.80 and not semantic_review:
            candidate["review_status"] = "accepted"
            candidate["provenance_status"] = "ready"
            candidate["gate_reasons"] = []
            accepted.append(candidate)
        elif confidence >= 0.55 and quality >= 0.55:
            candidate["review_status"] = "needs_human_review"
            candidate["gate_reasons"] = semantic_review or ["context_or_variable_review_required"]
            needs_review.append(candidate)
        else:
            candidate["review_status"] = "rejected"
            candidate["gate_reasons"] = ["quality_or_confidence_below_gate"]
            rejected.append(candidate)

    return {
        "accepted": accepted,
        "needs_human_review": needs_review,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "needs_human_review_count": len(needs_review),
        "rejected_count": len(rejected),
    }


def compare_external_ingestion_readback(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_documents = {str(item.get("sha256")): item for item in expected.get("documents") or []}
    actual_documents = {str(item.get("sha256")): item for item in actual.get("documents") or []}
    expected_units = {str(item.get("dedup_key")): item for item in expected.get("knowledge_units") or []}
    actual_units = {str(item.get("dedup_key")): item for item in actual.get("knowledge_units") or []}

    missing_documents = sorted(key for key in expected_documents if key not in actual_documents)
    missing_units = sorted(key for key in expected_units if key not in actual_units)
    chunk_mismatches = []
    for digest, item in expected_documents.items():
        actual_item = actual_documents.get(digest)
        if actual_item and int(item.get("chunk_count") or 0) != int(actual_item.get("chunk_count") or 0):
            chunk_mismatches.append(digest)
    provenance_match_count = sum(1 for key in expected_units if actual_units.get(key, {}).get("provenance_match") is True)
    orphan_chunks = int(actual.get("orphan_chunks") or 0)
    passed = not missing_documents and not missing_units and not chunk_mismatches and orphan_chunks == 0
    return {
        "passed": passed,
        "missing_documents": missing_documents,
        "missing_knowledge_units": missing_units,
        "chunk_count_mismatches": chunk_mismatches,
        "orphan_chunks": orphan_chunks,
        "provenance_match_count": provenance_match_count,
    }


def _extract_preview(path: Path, *, max_pdf_pages: int = 12) -> tuple[str, dict[str, Any]]:
    extension = path.suffix.lower()
    if extension == ".pdf":
        from services.ingest_service.ocr_pdf import extract_pdf_text_pages

        pages = extract_pdf_text_pages(path, max_pages=max_pdf_pages)
        text = "\n".join(str(page.text or "") for page in pages)
        return text, {"sampled_pages": len(pages), "parser": "pdf_text_layer"}
    if extension == ".docx":
        from services.ingest_service.parsers.docx_parser import parse_docx_to_blocks

        blocks = parse_docx_to_blocks(path)
        text = "\n".join(str(block.text or "") for block in blocks)
        return text, {"sampled_blocks": len(blocks), "parser": "docx"}
    return "", {"parser": None}


def _garbled_ratio(text: str) -> float:
    if not text:
        return 1.0
    bad = text.count("\ufffd") + text.count("\x00")
    printable = sum(1 for char in text if char.isprintable() or char.isspace())
    return max(bad / max(1, len(text)), 1.0 - printable / max(1, len(text)))


def _score_preview(filename: str, text: str, *, extension: str) -> dict[str, float]:
    normalized = re.sub(r"\s+", " ", f"{filename} {text[:100000]}").casefold()
    high_hits = sum(1 for term in HIGH_RELEVANCE_TERMS if term in normalized)
    medium_hits = sum(1 for term in MEDIUM_RELEVANCE_TERMS if term in normalized)
    relevance = min(1.0, high_hits * 0.14 + medium_hits * 0.045)
    if "pv/t" in normalized or "光伏" in normalized:
        relevance = max(0.0, relevance - 0.16)
    if "heat transfer" in normalized or "传热学" in normalized:
        relevance = min(1.0, relevance + 0.05)

    chars = len(text.strip())
    quality = min(1.0, chars / 12000.0)
    quality *= max(0.0, 1.0 - _garbled_ratio(text) * 5.0)
    if extension == ".docx":
        quality = min(1.0, quality + 0.08)

    novelty_hits = sum(1 for term in NOVELTY_TERMS if term in normalized)
    novelty = min(1.0, novelty_hits * 0.16)
    provenance = 0.35
    if any(term in normalized for term in ("ashrae", "intel", "guide", "guideline", "standard", "white paper", "doi", "abstract")):
        provenance += 0.35
    if re.search(r"\b(?:19|20)\d{2}\b", normalized):
        provenance += 0.15
    provenance = min(1.0, provenance)

    structure_signals = len(re.findall(r"(?:=|\bpa\b|\bkpa\b|l/min|w/[mk]|kg/s|reynolds|雷诺|公式|参数)", normalized))
    structure = min(1.0, structure_signals / 12.0)
    final = 0.40 * relevance + 0.20 * quality + 0.15 * novelty + 0.15 * provenance + 0.10 * structure
    if "pv/t" in normalized or "光伏" in normalized:
        final = max(0.0, final - 0.18)
    if (" air " in f" {normalized} " or "空气" in normalized) and not any(
        term in normalized for term in ("liquid cooling", "液冷", "coolant", "冷却液")
    ):
        final = max(0.0, final - 0.10)
    return {
        "relevance_score": round(relevance, 4),
        "quality_score": round(quality, 4),
        "novelty_score": round(novelty, 4),
        "provenance_score": round(provenance, 4),
        "structure_score": round(structure, 4),
        "final_score": round(final, 4),
    }


def inspect_and_score_inventory(inventory_report: dict[str, Any]) -> dict[str, Any]:
    report = dict(inventory_report)
    inspected: list[dict[str, Any]] = []
    ocr_required = 0
    for raw in inventory_report.get("files") or []:
        item = dict(raw)
        if item.get("excluded"):
            inspected.append(item)
            continue
        path = Path(str(item.get("absolute_path") or ""))
        try:
            preview, parser_meta = _extract_preview(path)
        except Exception as exc:
            item.update(
                {
                    "text_extractable": False,
                    "excluded": True,
                    "exclusion_reason": f"parse_preview_failed:{type(exc).__name__}",
                    "selection_status": "excluded",
                    "selection_reason": "parse_preview_failed",
                }
            )
            inspected.append(item)
            continue

        preview_chars = len(preview.strip())
        text_extractable = preview_chars >= 500 and _garbled_ratio(preview) <= 0.08
        item["text_extractable"] = text_extractable
        item["text_preview_chars"] = preview_chars
        item["text_preview"] = re.sub(r"\s+", " ", preview).strip()[:800]
        item["parser_details"] = parser_meta
        item["estimated_chunks"] = max(1, round(preview_chars / 1200)) if text_extractable else 0
        if not text_extractable:
            item["excluded"] = True
            item["exclusion_reason"] = "ocr_required" if path.suffix.lower() == ".pdf" else "insufficient_text"
            item["selection_status"] = "excluded"
            item["selection_reason"] = item["exclusion_reason"]
            if item["exclusion_reason"] == "ocr_required":
                ocr_required += 1
        else:
            item.update(_score_preview(item["filename"], preview, extension=path.suffix.lower()))
            item["selection_reason"] = "scored_parseable_candidate"
        inspected.append(item)

    summary = dict(inventory_report.get("summary") or {})
    summary["ocr_required_count"] = ocr_required
    summary["valid_candidate_count"] = sum(1 for item in inspected if not item.get("excluded"))
    report["files"] = inspected
    report["summary"] = summary
    return report


def parse_external_source(path: str | Path, cfg: Any, *, run_id: str) -> dict[str, Any]:
    from dataclasses import replace
    from services.ingest_service.chunking import build_chunk_context, chunk_blocks_to_rows

    source_path = Path(path)
    extension = source_path.suffix.lower()
    if extension == ".pdf":
        from services.ingest_service.ingest_pdf_rich import pages_to_blocks
        from services.ingest_service.ocr_pdf import extract_pdf_text_pages

        pages = extract_pdf_text_pages(source_path)
        blocks = pages_to_blocks(pages, cfg)
        parser_name = "pdf_text_layer"
        page_count = len(pages)
    elif extension == ".docx":
        from services.ingest_service.parsers.docx_parser import parse_docx_to_blocks

        blocks = parse_docx_to_blocks(source_path)
        parser_name = "docx"
        page_count = None
    else:
        return {"status": "unsupported", "quality_passed": False, "chunk_count": 0, "rows": [], "error": "unsupported_format"}

    block_text = "\n".join(str(block.text or "") for block in blocks)
    chunk_context = replace(
        build_chunk_context(cfg),
        semantic_split_enable=False,
        use_token_budget=False,
    )
    rows = chunk_blocks_to_rows(blocks, ctx=chunk_context)
    enriched_rows = []
    digest = sha256_file(source_path)
    for row in rows:
        meta = dict(row.meta_json) if isinstance(row.meta_json, dict) else {}
        meta.update({"source_file": source_path.name, "source_sha256": digest, "external_ingestion_run_id": run_id})
        enriched_rows.append(replace(row, meta_json=meta))
    chars = len(block_text.strip())
    empty_rows = sum(1 for row in enriched_rows if not str(row.text or "").strip())
    quality_passed = chars >= 800 and bool(enriched_rows) and empty_rows == 0 and _garbled_ratio(block_text) <= 0.08
    return {
        "status": "parsed" if quality_passed else "failed_quality_gate",
        "quality_passed": quality_passed,
        "parser": parser_name,
        "page_count": page_count,
        "character_count": chars,
        "garbled_ratio": round(_garbled_ratio(block_text), 6),
        "chunk_count": len(enriched_rows),
        "empty_chunk_count": empty_rows,
        "rows": enriched_rows,
        "sha256": digest,
        "title": source_path.stem,
        "mime": "application/pdf" if extension == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "semantic_model_used": False,
    }
