from __future__ import annotations

from copy import deepcopy
from typing import Any


REVIEW_CASE_REQUIRED_FIELDS = {
    "case_id",
    "query",
    "category",
    "answerable",
    "expected_chunk_ids",
    "expected_document_ids",
    "acceptable_chunk_ids",
    "acceptable_document_ids",
    "must_not_return_chunk_ids",
    "must_not_return_document_ids",
    "human_validated",
    "validation_status",
    "validation_note",
    "annotation_source",
    "query_intent",
    "required_concepts",
    "confusing_concepts",
    "original_annotation",
}


_CATEGORY_MAP = {
    "legacy_protection": "old_corpus",
    "new_external_source": "new_source",
    "synonym_paraphrase": "paraphrase",
    "confusion_negative": "negative",
}


def _int_list(value: Any) -> list[int]:
    return [int(item) for item in (value or [])]


def build_review_ready_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(dataset.get("metadata") or {})
    cases: list[dict[str, Any]] = []
    for original_value in dataset.get("cases") or []:
        original = dict(original_value)
        expected_chunks = _int_list(original.get("relevant_chunk_ids"))
        expected_documents = _int_list(original.get("expected_document_ids"))
        acceptable_chunks = _int_list(original.get("acceptable_chunk_ids"))
        cases.append(
            {
                "case_id": str(original.get("case_id") or ""),
                "query": str(original.get("query") or ""),
                "category": _CATEGORY_MAP.get(
                    str(original.get("corpus_scope") or ""),
                    str(original.get("corpus_scope") or original.get("category") or "pending"),
                ),
                "original_category": original.get("category"),
                "corpus_scope": original.get("corpus_scope"),
                "answerable": bool(expected_chunks or expected_documents),
                "expected_chunk_ids": expected_chunks,
                "expected_document_ids": expected_documents,
                "acceptable_chunk_ids": acceptable_chunks,
                "acceptable_document_ids": list(expected_documents),
                "must_not_return_chunk_ids": [],
                "must_not_return_document_ids": _int_list(original.get("forbidden_document_ids")),
                "human_validated": False,
                "validation_status": "pending",
                "validation_note": "",
                "annotation_source": "external_source_retrieval_holdout_30_v1.0",
                "query_intent": str(original.get("query_style") or ""),
                "required_concepts": [],
                "confusing_concepts": [],
                "expected_topic": original.get("expected_topic"),
                "expected_source_filenames": list(original.get("expected_source_filenames") or []),
                "notes": original.get("notes"),
                "original_annotation": deepcopy(original),
            }
        )
    return {
        "metadata": {
            **metadata,
            "dataset_id": "ExternalSource-Retrieval-Holdout-30-Review-Ready",
            "source_dataset_id": metadata.get("dataset_id"),
            "source_dataset_version": metadata.get("version"),
            "review_schema_version": "1.0",
            "case_count": len(cases),
            "human_validated": False,
            "validation_status": "pending",
            "conversion_type": "deterministic_annotation_preserving",
            "external_model_used": False,
        },
        "cases": cases,
    }


def validate_review_ready_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    cases = list(dataset.get("cases") or [])
    errors: list[str] = []
    ids: list[str] = []
    for index, value in enumerate(cases):
        if not isinstance(value, dict):
            errors.append(f"case_{index}_not_object")
            continue
        missing = REVIEW_CASE_REQUIRED_FIELDS - set(value)
        if missing:
            errors.append(f"case_{value.get('case_id', index)}_missing:{','.join(sorted(missing))}")
        case_id = str(value.get("case_id") or "")
        ids.append(case_id)
        if not case_id or not str(value.get("query") or "").strip():
            errors.append(f"case_{index}_identity_or_query_empty")
        for key in (
            "expected_chunk_ids",
            "expected_document_ids",
            "acceptable_chunk_ids",
            "acceptable_document_ids",
            "must_not_return_chunk_ids",
            "must_not_return_document_ids",
            "required_concepts",
            "confusing_concepts",
        ):
            if not isinstance(value.get(key), list):
                errors.append(f"case_{case_id}_{key}_not_list")
        if value.get("human_validated") is not False:
            errors.append(f"case_{case_id}_automatic_human_validation_forbidden")
        if value.get("validation_status") not in {"pending", "validated", "rejected", "needs_revision"}:
            errors.append(f"case_{case_id}_invalid_validation_status")
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        errors.append("duplicate_case_ids")
    human_count = sum(bool(case.get("human_validated")) for case in cases if isinstance(case, dict))
    pending_count = sum(case.get("validation_status") == "pending" for case in cases if isinstance(case, dict))
    return {
        "passed": not errors,
        "errors": errors,
        "case_count": len(cases),
        "unique_case_count": len(set(ids)),
        "human_validated_count": human_count,
        "pending_count": pending_count,
        "schema_version": (dataset.get("metadata") or {}).get("review_schema_version"),
    }


def build_holdout_schema() -> dict[str, Any]:
    integer_array = {"type": "array", "items": {"type": "integer"}}
    string_array = {"type": "array", "items": {"type": "string"}}
    properties: dict[str, Any] = {
        "case_id": {"type": "string", "minLength": 1},
        "query": {"type": "string", "minLength": 1},
        "category": {"enum": ["old_corpus", "new_source", "paraphrase", "negative"]},
        "answerable": {"type": "boolean"},
        "human_validated": {"const": False},
        "validation_status": {"enum": ["pending", "validated", "rejected", "needs_revision"]},
        "validation_note": {"type": "string"},
        "annotation_source": {"type": "string"},
        "query_intent": {"type": "string"},
        "original_annotation": {"type": "object"},
    }
    for key in (
        "expected_chunk_ids",
        "expected_document_ids",
        "acceptable_chunk_ids",
        "acceptable_document_ids",
        "must_not_return_chunk_ids",
        "must_not_return_document_ids",
    ):
        properties[key] = integer_array
    properties["required_concepts"] = string_array
    properties["confusing_concepts"] = string_array
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ExternalSource Retrieval Holdout Review Ready",
        "type": "object",
        "required": ["metadata", "cases"],
        "properties": {
            "metadata": {"type": "object"},
            "cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": sorted(REVIEW_CASE_REQUIRED_FIELDS),
                    "properties": properties,
                },
            },
        },
    }
