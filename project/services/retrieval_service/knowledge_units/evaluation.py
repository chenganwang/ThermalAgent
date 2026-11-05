from __future__ import annotations

from collections import Counter
import json
import re
from pathlib import Path
from typing import Any

from .adapter import KnowledgeUnitsRetrievalAdapter
from .query_builder import normalize_unit_types
from .stopwords import LOW_VALUE_MATCH_TERMS, is_stopword


DEFAULT_SHADOW_QUERY_SET = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_queries.jsonl"
DEFAULT_PHASE2E_BASELINE_REPORT_JSON = Path("runtime") / "knowledge_unit_candidates" / "knowledge_unit_shadow_evaluation_report.json"
JUDGMENTS = {"useful", "partial", "wrong", "unjudged"}
PHASE2E_BASELINE_METRICS = {
    "precision_at_1": 0.2917,
    "precision_at_3": 0.2778,
    "unit_type_match_rate": 0.375,
    "provenance_ready_rate": 1.0,
}
READINESS_THRESHOLDS = {
    "precision_at_1": 0.50,
    "precision_at_3": 0.45,
    "unit_type_match_rate": 0.55,
    "provenance_ready_rate": 1.0,
}
GENERIC_EXPECTED_TERMS = {
    "and",
    "architecture",
    "case",
    "component",
    "concept",
    "cooling",
    "evidence",
    "fault",
    "heat transfer",
    "liquid",
    "liquid cooling",
    "loop",
    "parameter",
    "risk",
    "source",
    "system",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).lower()).strip()


def _terms(values: Any) -> list[str]:
    if values is None:
        return []
    raw = values if isinstance(values, list) else [values]
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        item = _norm(value)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _specific_terms(values: Any) -> list[str]:
    return [term for term in _terms(values) if term not in GENERIC_EXPECTED_TERMS]


def _hit_blob(hit: dict[str, Any]) -> str:
    fields = (
        "unit_code",
        "dedup_key",
        "unit_type",
        "canonical_name",
        "content",
        "match_reason",
    )
    return " ".join(_norm(hit.get(field)) for field in fields)


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted((str(key), int(value)) for key, value in counter.items()))


def _metric(value: Any) -> float:
    try:
        return round(float(value), 4)
    except Exception:
        return 0.0


def _match_reason_terms(reason: Any) -> list[str]:
    text = _norm(reason)
    if not text:
        return []
    terms: list[str] = []
    for chunk in re.split(r"[;|]", text):
        if ":" in chunk:
            chunk = chunk.split(":", 1)[1]
        terms.extend(item.strip() for item in chunk.split(",") if item.strip())
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        item = term.strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def load_shadow_query_set(path: str | Path = DEFAULT_SHADOW_QUERY_SET) -> list[dict[str, Any]]:
    input_path = Path(path)
    queries: list[dict[str, Any]] = []
    for line_no, raw in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {input_path}:{line_no}: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"query spec must be an object at {input_path}:{line_no}")
        queries.append(validate_query_spec(item, line_no=line_no))
    return queries


def validate_query_spec(spec: dict[str, Any], *, line_no: int | None = None) -> dict[str, Any]:
    label = f" line {line_no}" if line_no is not None else ""
    query_id = _text(spec.get("query_id"))
    query = _text(spec.get("query"))
    category = _text(spec.get("category"))
    difficulty = _text(spec.get("difficulty"))
    expected_unit_types = normalize_unit_types(spec.get("expected_unit_types") or [])
    expected_keywords = _terms(spec.get("expected_keywords") or [])
    expected_canonical_names = _terms(spec.get("expected_canonical_names") or [])

    missing = [
        name
        for name, value in (
            ("query_id", query_id),
            ("query", query),
            ("category", category),
            ("difficulty", difficulty),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"missing required fields{label}: {', '.join(missing)}")
    if not expected_unit_types:
        raise ValueError(f"expected_unit_types must contain at least one valid type{label}")
    if not expected_keywords and not expected_canonical_names:
        raise ValueError(f"expected_keywords or expected_canonical_names is required{label}")

    out = dict(spec)
    out["query_id"] = query_id
    out["query"] = query
    out["category"] = category
    out["difficulty"] = difficulty
    out["expected_unit_types"] = expected_unit_types
    out["expected_keywords"] = expected_keywords
    out["expected_canonical_names"] = expected_canonical_names
    return out


def judge_hit(query_spec: dict[str, Any], hit: dict[str, Any], *, rank: int) -> dict[str, Any]:
    expected_types = set(normalize_unit_types(query_spec.get("expected_unit_types") or []))
    expected_terms = _specific_terms(query_spec.get("expected_keywords") or []) + _specific_terms(
        query_spec.get("expected_canonical_names") or []
    )
    hit_type = _norm(hit.get("unit_type"))
    blob = _hit_blob(hit)
    unit_type_match = bool(expected_types and hit_type in expected_types)
    keyword_matches = [term for term in expected_terms if term and term in blob]
    keyword_match = bool(keyword_matches)

    if not expected_types and not expected_terms:
        judgment = "unjudged"
    elif unit_type_match and keyword_match:
        judgment = "useful"
    elif unit_type_match or keyword_match:
        judgment = "partial"
    else:
        judgment = "wrong"

    return {
        "rank": int(rank),
        "judgment": judgment,
        "unit_type_match": unit_type_match,
        "keyword_match": keyword_match,
        "matched_expected_terms": keyword_matches[:10],
        "unit_code": hit.get("unit_code"),
        "dedup_key": hit.get("dedup_key"),
        "unit_type": hit.get("unit_type"),
        "canonical_name": hit.get("canonical_name"),
        "document_id": hit.get("document_id"),
        "source_chunk_id": hit.get("source_chunk_id"),
        "provenance_status": hit.get("provenance_status"),
        "match_reason": hit.get("match_reason"),
        "score": hit.get("score"),
        "score_breakdown": hit.get("score_breakdown") or {},
    }


def evaluate_query_result(query_spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    hits = [dict(hit) for hit in result.get("hits") or [] if isinstance(hit, dict)]
    judged_hits = [judge_hit(query_spec, hit, rank=index + 1) for index, hit in enumerate(hits)]
    useful_count = sum(1 for hit in judged_hits if hit["judgment"] == "useful")
    partial_count = sum(1 for hit in judged_hits if hit["judgment"] == "partial")
    wrong_count = sum(1 for hit in judged_hits if hit["judgment"] == "wrong")
    unjudged_count = sum(1 for hit in judged_hits if hit["judgment"] == "unjudged")
    top1 = judged_hits[0]["judgment"] if judged_hits else None

    return {
        "query_id": query_spec.get("query_id"),
        "query": query_spec.get("query"),
        "category": query_spec.get("category"),
        "difficulty": query_spec.get("difficulty"),
        "expected_unit_types": list(query_spec.get("expected_unit_types") or []),
        "expected_keywords": list(query_spec.get("expected_keywords") or []),
        "expected_canonical_names": list(query_spec.get("expected_canonical_names") or []),
        "retrieval_status": result.get("status"),
        "hit_count": len(hits),
        "top1_judgment": top1,
        "useful_hit_count": useful_count,
        "partial_hit_count": partial_count,
        "wrong_hit_count": wrong_count,
        "unjudged_hit_count": unjudged_count,
        "has_useful_hit": useful_count > 0,
        "has_relevant_hit": useful_count + partial_count > 0,
        "top_hits": judged_hits,
        "error_type": result.get("error_type"),
        "error": result.get("error"),
    }


def build_evaluation_payload(query_evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in query_evaluations if isinstance(item, dict)]
    query_count = len(rows)
    hit_query_count = sum(1 for item in rows if int(item.get("hit_count") or 0) > 0)
    miss_query_count = query_count - hit_query_count
    total_hit_count = sum(int(item.get("hit_count") or 0) for item in rows)
    useful_hit_count = sum(int(item.get("useful_hit_count") or 0) for item in rows)
    partial_hit_count = sum(int(item.get("partial_hit_count") or 0) for item in rows)
    wrong_hit_count = sum(int(item.get("wrong_hit_count") or 0) for item in rows)
    unjudged_hit_count = sum(int(item.get("unjudged_hit_count") or 0) for item in rows)

    top1_useful = sum(1 for item in rows if item.get("top1_judgment") == "useful")
    top3_useful = 0
    top3_denominator = 0
    unit_type_matches = 0
    provenance_ready = 0
    counts_by_unit_type: Counter[str] = Counter()
    counts_by_category: Counter[str] = Counter()
    false_positive_examples: list[dict[str, Any]] = []
    miss_examples: list[dict[str, Any]] = []
    error_examples: list[dict[str, Any]] = []

    for item in rows:
        counts_by_category[_text(item.get("category")) or "unknown"] += 1
        top_hits = [dict(hit) for hit in item.get("top_hits") or [] if isinstance(hit, dict)]
        for hit in top_hits:
            counts_by_unit_type[_text(hit.get("unit_type")) or "unknown"] += 1
            if hit.get("unit_type_match"):
                unit_type_matches += 1
            if _norm(hit.get("provenance_status")) == "ready":
                provenance_ready += 1
        first_three = top_hits[:3]
        top3_denominator += len(first_three)
        top3_useful += sum(1 for hit in first_three if hit.get("judgment") == "useful")
        if not top_hits and len(miss_examples) < 10:
            miss_examples.append(
                {
                    "query_id": item.get("query_id"),
                    "query": item.get("query"),
                    "category": item.get("category"),
                    "expected_unit_types": item.get("expected_unit_types"),
                    "expected_keywords": item.get("expected_keywords"),
                    "expected_canonical_names": item.get("expected_canonical_names"),
                }
            )
        for hit in top_hits:
            if hit.get("judgment") == "wrong" and len(false_positive_examples) < 10:
                false_positive_examples.append(
                    {
                        "query_id": item.get("query_id"),
                        "query": item.get("query"),
                        "rank": hit.get("rank"),
                        "unit_type": hit.get("unit_type"),
                        "canonical_name": hit.get("canonical_name"),
                        "dedup_key": hit.get("dedup_key"),
                        "match_reason": hit.get("match_reason"),
                    }
                )
        if item.get("retrieval_status") == "error" and len(error_examples) < 10:
            error_examples.append(
                {
                    "query_id": item.get("query_id"),
                    "query": item.get("query"),
                    "error_type": item.get("error_type"),
                    "error": item.get("error"),
                }
            )

    status = "ok" if not error_examples else "error"
    return {
        "status": status,
        "query_count": query_count,
        "hit_query_count": hit_query_count,
        "miss_query_count": miss_query_count,
        "total_hit_count": total_hit_count,
        "useful_hit_count": useful_hit_count,
        "partial_hit_count": partial_hit_count,
        "wrong_hit_count": wrong_hit_count,
        "unjudged_hit_count": unjudged_hit_count,
        "precision_at_1": round(top1_useful / query_count, 4) if query_count else 0.0,
        "precision_at_3": round(top3_useful / top3_denominator, 4) if top3_denominator else 0.0,
        "unit_type_match_rate": round(unit_type_matches / total_hit_count, 4) if total_hit_count else 0.0,
        "provenance_ready_rate": round(provenance_ready / total_hit_count, 4) if total_hit_count else 0.0,
        "counts_by_unit_type": _counter_dict(counts_by_unit_type),
        "counts_by_query_category": _counter_dict(counts_by_category),
        "false_positive_examples": false_positive_examples,
        "miss_examples": miss_examples,
        "error_examples": error_examples,
        "query_results": rows,
        "database_written": False,
        "readonly": True,
        "default_agent_dependency": False,
        "fusion_enabled": False,
        "external_api_called": False,
        "next_steps": [
            "Review useful, partial, and wrong examples before designing any chunk plus knowledge_units fusion policy.",
            "Keep knowledge_units optional and shadow-only until quality is good enough for a separate integration phase.",
        ],
    }


def load_phase2e_baseline_metrics(_path: str | Path = DEFAULT_PHASE2E_BASELINE_REPORT_JSON) -> dict[str, float]:
    """Return the frozen Phase 2E baseline requested for Phase 2F comparison."""

    return {key: _metric(value) for key, value in PHASE2E_BASELINE_METRICS.items()}


def load_evaluation_report(path: str | Path = DEFAULT_PHASE2E_BASELINE_REPORT_JSON) -> dict[str, Any]:
    input_path = Path(path)
    if not input_path.exists():
        return {}
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def attach_before_after_metrics(payload: dict[str, Any], baseline_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    baseline = {key: _metric(value) for key, value in (baseline_metrics or PHASE2E_BASELINE_METRICS).items()}
    current = {
        "precision_at_1": _metric(payload.get("precision_at_1")),
        "precision_at_3": _metric(payload.get("precision_at_3")),
        "unit_type_match_rate": _metric(payload.get("unit_type_match_rate")),
        "provenance_ready_rate": _metric(payload.get("provenance_ready_rate")),
    }
    metric_delta = {
        key: round(current.get(key, 0.0) - baseline.get(key, 0.0), 4)
        for key in ("precision_at_1", "precision_at_3", "unit_type_match_rate", "provenance_ready_rate")
    }
    threshold_met = (
        current["precision_at_1"] >= READINESS_THRESHOLDS["precision_at_1"]
        and current["precision_at_3"] >= READINESS_THRESHOLDS["precision_at_3"]
        and current["unit_type_match_rate"] >= READINESS_THRESHOLDS["unit_type_match_rate"]
        and current["provenance_ready_rate"] >= READINESS_THRESHOLDS["provenance_ready_rate"]
    )
    readiness_decision = (
        "ready_for_larger_shadow_evaluation_or_ku_expansion"
        if threshold_met
        else "not_ready_for_fusion_continue_adapter_or_data_improvement"
    )
    payload.update(
        {
            "baseline_metrics": baseline,
            "current_metrics": current,
            "metric_delta": metric_delta,
            "current_precision_at_1": current["precision_at_1"],
            "current_precision_at_3": current["precision_at_3"],
            "current_unit_type_match_rate": current["unit_type_match_rate"],
            "current_provenance_ready_rate": current["provenance_ready_rate"],
            "delta_precision_at_1": metric_delta["precision_at_1"],
            "delta_precision_at_3": metric_delta["precision_at_3"],
            "delta_unit_type_match_rate": metric_delta["unit_type_match_rate"],
            "delta_provenance_ready_rate": metric_delta["provenance_ready_rate"],
            "readiness_decision": readiness_decision,
            "readiness_thresholds": dict(READINESS_THRESHOLDS),
            "fusion_ready": False,
            "retrieval_main_path_changed": False,
            "agent_answer_contract_changed": False,
        }
    )
    return payload


def build_false_positive_analysis_payload(baseline_report: dict[str, Any]) -> dict[str, Any]:
    rows = [dict(item) for item in baseline_report.get("query_results") or [] if isinstance(item, dict)]
    top1_bad: list[dict[str, Any]] = []
    false_positive_unit_types: Counter[str] = Counter()
    generic_term_counter: Counter[str] = Counter()
    content_overwide_examples: list[dict[str, Any]] = []
    canonical_name_hit_insufficient: list[dict[str, Any]] = []
    expected_type_mismatches: list[dict[str, Any]] = []
    query_category_type_mismatches: list[dict[str, Any]] = []

    for item in rows:
        top_hits = [dict(hit) for hit in item.get("top_hits") or [] if isinstance(hit, dict)]
        top1 = top_hits[0] if top_hits else {}
        top1_judgment = str(item.get("top1_judgment") or "")
        if top1_judgment in {"wrong", "partial"}:
            top1_bad.append(
                {
                    "query_id": item.get("query_id"),
                    "query": item.get("query"),
                    "category": item.get("category"),
                    "top1_judgment": top1_judgment,
                    "top1_unit_type": top1.get("unit_type"),
                    "top1_canonical_name": top1.get("canonical_name"),
                    "top1_match_reason": top1.get("match_reason"),
                }
            )
        for hit in top_hits:
            if hit.get("judgment") == "wrong":
                false_positive_unit_types[_text(hit.get("unit_type")) or "unknown"] += 1
                reason_terms = _match_reason_terms(hit.get("match_reason"))
                generic_terms = [
                    term
                    for term in reason_terms
                    if is_stopword(term) or term.replace(" ", "_") in LOW_VALUE_MATCH_TERMS
                ]
                for term in generic_terms:
                    generic_term_counter[term] += 1
                if generic_terms and len(content_overwide_examples) < 12:
                    content_overwide_examples.append(
                        {
                            "query_id": item.get("query_id"),
                            "rank": hit.get("rank"),
                            "unit_type": hit.get("unit_type"),
                            "canonical_name": hit.get("canonical_name"),
                            "match_reason": hit.get("match_reason"),
                            "generic_terms": generic_terms[:8],
                        }
                    )
            if not hit.get("unit_type_match") and len(expected_type_mismatches) < 12:
                expected_type_mismatches.append(
                    {
                        "query_id": item.get("query_id"),
                        "rank": hit.get("rank"),
                        "expected_unit_types": item.get("expected_unit_types"),
                        "actual_unit_type": hit.get("unit_type"),
                        "canonical_name": hit.get("canonical_name"),
                    }
                )
        expected_names = {_norm(value).replace(" ", "_") for value in item.get("expected_canonical_names") or []}
        lower_rank_expected = [
            hit
            for hit in top_hits[1:]
            if _norm(hit.get("canonical_name")).replace(" ", "_") in expected_names
            or _norm(hit.get("dedup_key")).split(":")[-1] in expected_names
        ]
        if top1_judgment in {"wrong", "partial"} and lower_rank_expected and len(canonical_name_hit_insufficient) < 12:
            canonical_name_hit_insufficient.append(
                {
                    "query_id": item.get("query_id"),
                    "top1_canonical_name": top1.get("canonical_name"),
                    "lower_rank_expected": [
                        {
                            "rank": hit.get("rank"),
                            "unit_type": hit.get("unit_type"),
                            "canonical_name": hit.get("canonical_name"),
                            "match_reason": hit.get("match_reason"),
                        }
                        for hit in lower_rank_expected[:3]
                    ],
                }
            )
        category = _text(item.get("category"))
        if category in {"concept", "parameter", "component", "fault_case"} and top1:
            if _text(top1.get("unit_type")) != category and len(query_category_type_mismatches) < 12:
                query_category_type_mismatches.append(
                    {
                        "query_id": item.get("query_id"),
                        "category": category,
                        "top1_unit_type": top1.get("unit_type"),
                        "top1_canonical_name": top1.get("canonical_name"),
                    }
                )

    summary = {
        "top1_wrong_or_partial_count": len(top1_bad),
        "false_positive_unit_types": _counter_dict(false_positive_unit_types),
        "generic_term_matches": _counter_dict(generic_term_counter),
        "content_field_overwide": bool(content_overwide_examples),
        "canonical_name_hit_insufficient_count": len(canonical_name_hit_insufficient),
        "expected_unit_type_mismatch_count": len(expected_type_mismatches),
        "query_category_type_mismatch_count": len(query_category_type_mismatches),
    }
    return {
        "phase": "2F",
        "status": "ok" if rows else "missing_baseline_report",
        "source_report": str(DEFAULT_PHASE2E_BASELINE_REPORT_JSON),
        "baseline_metrics": load_phase2e_baseline_metrics(),
        "summary": summary,
        "top1_wrong_or_partial_queries": top1_bad,
        "false_positive_unit_types": summary["false_positive_unit_types"],
        "generic_term_matches": summary["generic_term_matches"],
        "content_overwide_examples": content_overwide_examples,
        "canonical_name_hit_insufficient": canonical_name_hit_insufficient,
        "expected_type_mismatches": expected_type_mismatches,
        "query_category_type_mismatches": query_category_type_mismatches,
        "analysis_notes": [
            "Phase 2E wrong hits were dominated by generic keyword matches and SQL-result order, especially component/gpu rows.",
            "Broad content and meta_json matching allowed terms such as in, and, source, liquid, cooling, case, and system to lift unrelated rows.",
            "Several expected canonical names were present lower in the result list, indicating ranking weakness rather than pure recall absence.",
        ],
        "database_written": False,
        "readonly": True,
        "external_api_called": False,
        "default_agent_dependency": False,
        "fusion_ready": False,
    }


def build_precision_improvement_payload(
    current_payload: dict[str, Any],
    *,
    baseline_report: dict[str, Any] | None = None,
    false_positive_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = attach_before_after_metrics(dict(current_payload), load_phase2e_baseline_metrics())
    baseline_rows = {
        str(item.get("query_id")): dict(item)
        for item in (baseline_report or {}).get("query_results", [])
        if isinstance(item, dict)
    }
    current_rows = {
        str(item.get("query_id")): dict(item)
        for item in enriched.get("query_results", [])
        if isinstance(item, dict)
    }
    examples_improved: list[dict[str, Any]] = []
    examples_still_wrong: list[dict[str, Any]] = []
    for query_id, current in current_rows.items():
        baseline = baseline_rows.get(query_id, {})
        baseline_top1 = baseline.get("top1_judgment")
        current_top1 = current.get("top1_judgment")
        if baseline_top1 != "useful" and current_top1 == "useful" and len(examples_improved) < 12:
            examples_improved.append(
                {
                    "query_id": query_id,
                    "query": current.get("query"),
                    "baseline_top1_judgment": baseline_top1,
                    "current_top1_judgment": current_top1,
                    "current_top1": (current.get("top_hits") or [{}])[0],
                }
            )
        if current_top1 in {"wrong", "partial"} and len(examples_still_wrong) < 12:
            examples_still_wrong.append(
                {
                    "query_id": query_id,
                    "query": current.get("query"),
                    "current_top1_judgment": current_top1,
                    "current_top1": (current.get("top_hits") or [{}])[0],
                }
            )

    return {
        "phase": "2F",
        "goal": "Improve optional read-only knowledge_units shadow retrieval precision without changing the main retrieval or agent path.",
        "status": enriched.get("status"),
        "baseline_metrics": enriched["baseline_metrics"],
        "current_metrics": enriched["current_metrics"],
        "metric_delta": enriched["metric_delta"],
        "false_positive_analysis_summary": (false_positive_analysis or {}).get("summary", {}),
        "scoring_changes": [
            "Canonical-name exact and partial matches receive the highest weights.",
            "Inferred unit_type hints add weight and wrong hinted types are penalized.",
            "Content keyword matches are lower weight than identity/canonical matches.",
            "Rows are now sorted stably by adapter score after SELECT-only candidate fetch.",
        ],
        "query_builder_changes": [
            "Query tokens are normalized and stopword-filtered for shadow retrieval only.",
            "Engineering phrases such as flow_rate, pressure_drop, cold_plate, coolant, PGW, CDU, TIM, and leakage are preserved.",
            "Shadow debug output includes tokens, filtered_tokens, unit_type_hints, match_terms, and query_debug_info.",
        ],
        "stopword_filtering_changes": [
            "Chinese generic QA words and English generic retrieval words are filtered from shadow scoring.",
            "Critical thermal engineering terms are explicitly protected from filtering.",
        ],
        "examples_improved": examples_improved,
        "examples_still_wrong": examples_still_wrong,
        "precision_at_1": enriched.get("precision_at_1"),
        "precision_at_3": enriched.get("precision_at_3"),
        "unit_type_match_rate": enriched.get("unit_type_match_rate"),
        "provenance_ready_rate": enriched.get("provenance_ready_rate"),
        "current_precision_at_1": enriched.get("current_precision_at_1"),
        "current_precision_at_3": enriched.get("current_precision_at_3"),
        "current_unit_type_match_rate": enriched.get("current_unit_type_match_rate"),
        "current_provenance_ready_rate": enriched.get("current_provenance_ready_rate"),
        "delta_precision_at_1": enriched.get("delta_precision_at_1"),
        "delta_precision_at_3": enriched.get("delta_precision_at_3"),
        "delta_unit_type_match_rate": enriched.get("delta_unit_type_match_rate"),
        "delta_provenance_ready_rate": enriched.get("delta_provenance_ready_rate"),
        "readiness_decision": enriched.get("readiness_decision"),
        "readiness_thresholds": enriched.get("readiness_thresholds"),
        "fusion_ready": False,
        "database_written": False,
        "readonly": True,
        "external_api_called": False,
        "default_agent_dependency": False,
        "retrieval_main_path_changed": False,
        "agent_answer_contract_changed": False,
        "query_count": enriched.get("query_count", 0),
        "hit_query_count": enriched.get("hit_query_count", 0),
        "miss_query_count": enriched.get("miss_query_count", 0),
        "total_hit_count": enriched.get("total_hit_count", 0),
        "useful_hit_count": enriched.get("useful_hit_count", 0),
        "partial_hit_count": enriched.get("partial_hit_count", 0),
        "wrong_hit_count": enriched.get("wrong_hit_count", 0),
        "unjudged_hit_count": enriched.get("unjudged_hit_count", 0),
        "counts_by_unit_type": enriched.get("counts_by_unit_type", {}),
        "counts_by_query_category": enriched.get("counts_by_query_category", {}),
        "next_steps": [
            "If the minimum precision goal is met, expand the shadow query set or accepted knowledge_units before any fusion design.",
            "If precision remains below target, continue adapter scoring work and inspect canonical_name, unit_type, and content atomization quality.",
            "Do not enable default agent dependency or formal chunk plus knowledge_units fusion in Phase 2F.",
        ],
    }


def run_shadow_evaluation(
    query_specs: list[dict[str, Any]],
    *,
    adapter: Any | None = None,
    top_k: int = 3,
    use_unit_type_filter: bool = False,
) -> dict[str, Any]:
    active_adapter = adapter or KnowledgeUnitsRetrievalAdapter(enabled=True)
    evaluations: list[dict[str, Any]] = []
    for spec in query_specs:
        query = _text(spec.get("query"))
        unit_types = spec.get("expected_unit_types") if use_unit_type_filter else []
        result = active_adapter.search(query, unit_types=unit_types, top_k=top_k)
        evaluations.append(evaluate_query_result(spec, dict(result)))
    payload = build_evaluation_payload(evaluations)
    payload["top_k"] = int(top_k)
    payload["unit_type_filter_enabled"] = bool(use_unit_type_filter)
    return payload


__all__ = [
    "DEFAULT_SHADOW_QUERY_SET",
    "DEFAULT_PHASE2E_BASELINE_REPORT_JSON",
    "GENERIC_EXPECTED_TERMS",
    "JUDGMENTS",
    "PHASE2E_BASELINE_METRICS",
    "READINESS_THRESHOLDS",
    "attach_before_after_metrics",
    "build_evaluation_payload",
    "build_false_positive_analysis_payload",
    "build_precision_improvement_payload",
    "evaluate_query_result",
    "judge_hit",
    "load_evaluation_report",
    "load_phase2e_baseline_metrics",
    "load_shadow_query_set",
    "run_shadow_evaluation",
    "validate_query_spec",
]
