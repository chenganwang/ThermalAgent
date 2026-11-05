from __future__ import annotations

from .contracts import KnowledgeUnitCandidate, VALID_UNIT_TYPES


def validate_candidate(candidate: KnowledgeUnitCandidate, min_confidence: float = 0.35) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    try:
        if candidate.unit_type not in VALID_UNIT_TYPES:
            warnings.append("invalid_unit_type")
        if not ((candidate.title or "").strip() or (candidate.content or "").strip()):
            warnings.append("missing_title_or_content")
        preview = ((candidate.source or {}).get("source_text_preview") or "").strip()
        if not preview:
            warnings.append("missing_source_text_preview")
        try:
            confidence = float(candidate.confidence)
        except Exception:
            confidence = -1.0
        if confidence < 0 or confidence > 1:
            warnings.append("invalid_confidence")
        elif confidence < float(min_confidence):
            warnings.append("low_confidence")
        if not (candidate.dedup_key or "").strip():
            warnings.append("missing_dedup_key")
    except Exception as exc:
        warnings.append(f"validator_error:{type(exc).__name__}")

    for warning in warnings:
        if warning not in candidate.warnings:
            candidate.warnings.append(warning)

    invalid = {
        "invalid_unit_type",
        "missing_title_or_content",
        "missing_source_text_preview",
        "invalid_confidence",
        "missing_dedup_key",
    }
    return not any(w in invalid for w in warnings), warnings
