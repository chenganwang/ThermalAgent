from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from typing import Any

from .component_extractor import extract as extract_component
from .concept_extractor import extract as extract_concept
from .fault_case_extractor import extract as extract_fault_case
from .formula_extractor import extract as extract_formula
from .parameter_extractor import extract as extract_parameter
from .standard_range_extractor import extract as extract_standard_range
from .thermal_path_extractor import extract as extract_thermal_path
from .contracts import KnowledgeUnitCandidate, truncate_preview
from .deduplicator import deduplicate_candidates
from .normalizer import compact_text, source_preview
from .validator import validate_candidate

EXTRACTORS = [
    extract_concept,
    extract_formula,
    extract_standard_range,
    extract_parameter,
    extract_component,
    extract_thermal_path,
    extract_fault_case,
]

TEXT_FIELDS = ("text", "content", "chunk_text", "page_content", "raw_text")


def _to_mapping(chunk: Any) -> dict[str, Any]:
    if chunk is None:
        return {}
    if isinstance(chunk, dict):
        return dict(chunk)
    if is_dataclass(chunk):
        try:
            return asdict(chunk)
        except Exception:
            return {}
    data: dict[str, Any] = {}
    for name in (
        "id",
        "chunk_id",
        "chunk_index",
        "doc_id",
        "document_id",
        "page_no",
        "page",
        "page_start",
        "page_end",
        "section_title",
        "section",
        "section_path",
        "source_file",
        "source",
        "title",
        "text",
        "content",
        "chunk_type",
        "type",
        "meta",
        "meta_json",
    ):
        if hasattr(chunk, name):
            data[name] = getattr(chunk, name)
    return data


def _decode_meta(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _first_present(mapping: dict[str, Any], names: tuple[str, ...] | list[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if value not in (None, ""):
            return value
    return None


def _safe_text(mapping: dict[str, Any]) -> str:
    for field in TEXT_FIELDS:
        value = mapping.get(field)
        if isinstance(value, str) and value.strip():
            return value
    meta = _decode_meta(mapping.get("meta_json") or mapping.get("meta"))
    for field in TEXT_FIELDS:
        value = meta.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _safe_source(mapping: dict[str, Any], text: str) -> dict[str, Any]:
    meta = _decode_meta(mapping.get("meta_json") or mapping.get("meta"))
    section = _first_present(mapping, ("section_title", "section", "section_path")) or _first_present(meta, ("section_title", "section", "section_path"))
    if isinstance(section, (list, tuple)):
        section = " > ".join(str(x) for x in section if str(x).strip())

    source_file = _first_present(mapping, ("source_file", "file", "filename", "title", "source")) or _first_present(
        meta, ("source_file", "file", "filename", "title", "source")
    )

    return {
        "document_id": _first_present(mapping, ("document_id", "doc_id")),
        "chunk_id": _first_present(mapping, ("chunk_id", "id", "chunk_index")),
        "page_no": _first_present(mapping, ("page_no", "page", "page_start")) or _first_present(meta, ("page_no", "page", "page_start")),
        "section_title": section,
        "source_file": source_file,
        "source_text_preview": truncate_preview(source_preview(text)),
    }


def _looks_like_noise(text: str) -> bool:
    normalized = compact_text(text)
    if not normalized:
        return True
    if len(normalized) < 6:
        return True
    lower = normalized.lower()
    if lower in {"references", "reference", "contents", "table of contents", "目录", "参考文献"}:
        return True
    if re.fullmatch(r"(?:\d+\s*){1,4}", normalized):
        return True
    if re.search(r"(?:^|\s)(contents|table of contents|目录)(?:\s|$)", lower) and len(normalized) < 260:
        return True
    if lower.startswith(("references ", "reference ")) and len(normalized) < 260:
        return True
    alnum_cjk = re.findall(r"[0-9A-Za-z\u4e00-\u9fff]", normalized)
    if len(alnum_cjk) / max(1, len(normalized)) < 0.25:
        return True
    return False


def extract_knowledge_units_from_chunk(chunk: dict) -> list[KnowledgeUnitCandidate]:
    mapping = _to_mapping(chunk)
    text = _safe_text(mapping)
    if _looks_like_noise(text):
        return []

    source = _safe_source(mapping, text)
    candidates: list[KnowledgeUnitCandidate] = []
    for extractor in EXTRACTORS:
        try:
            extracted = extractor(text, dict(source))
        except Exception as exc:
            extracted = [
                KnowledgeUnitCandidate(
                    unit_type="concept",
                    canonical_name="extractor_error",
                    title="Extractor error",
                    content="",
                    aliases=[],
                    properties={"extractor": getattr(extractor, "__module__", ""), "error": type(exc).__name__},
                    source=dict(source),
                    confidence=0.0,
                    extraction_method="rule_based",
                    dedup_key=f"extractor_error:{getattr(extractor, '__module__', 'unknown')}",
                    warnings=[f"extractor_error:{type(exc).__name__}"],
                )
            ]
        for candidate in extracted:
            candidate.source = dict(candidate.source or {})
            candidate.source["source_text_preview"] = truncate_preview(candidate.source.get("source_text_preview", ""))
            ok, _warnings = validate_candidate(candidate)
            if ok:
                candidates.append(candidate)

    return deduplicate_candidates(candidates)


def extract_knowledge_units_from_chunks(chunks: list[dict]) -> list[KnowledgeUnitCandidate]:
    candidates: list[KnowledgeUnitCandidate] = []
    for chunk in chunks or []:
        candidates.extend(extract_knowledge_units_from_chunk(chunk))
    return deduplicate_candidates(candidates)
