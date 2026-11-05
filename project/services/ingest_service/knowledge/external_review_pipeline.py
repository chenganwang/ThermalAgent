from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import json

from services.ingest_service.external_ingestion import connect_mysql, fetch_database_snapshot
from services.ingest_service.knowledge.db_writer import (
    preflight_validate_write_plan,
    write_knowledge_units_transactional,
)
from services.ingest_service.knowledge.writer_mapping import map_candidate_to_write_plan
from services.retrieval_service.config import AppConfig
from services.retrieval_service.knowledge_units.adapter import KnowledgeUnitsRetrievalAdapter
from services.retrieval_service.knowledge_units.evaluation import (
    load_shadow_query_set,
    run_shadow_evaluation,
)


def utc_review_run_id() -> str:
    return "external_ku_review_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json(path: str | Path, payload: Any) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )
    return output


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, default=json_default) + "\n" for row in rows),
        encoding="utf-8",
    )
    return output


def _decode_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def knowledge_unit_snapshot(cfg: AppConfig) -> dict[str, Any]:
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, unit_code, unit_type, title, summary, content, domain, source_doc_id, source_chunk_id, "
            "page_start, page_end, keywords, confidence_score, review_status, reviewer, meta_json, created_at, updated_at "
            "FROM knowledge_units ORDER BY id"
        )
        rows = []
        fingerprints: dict[str, str] = {}
        for raw in cursor.fetchall() or []:
            row = dict(raw)
            identity = str(row.get("unit_code") or row.get("id"))
            stable = {
                key: row.get(key)
                for key in (
                    "id", "unit_code", "unit_type", "title", "summary", "content", "domain",
                    "source_doc_id", "source_chunk_id", "page_start", "page_end", "keywords",
                    "confidence_score", "review_status", "reviewer", "meta_json", "created_at",
                )
            }
            fingerprints[identity] = sha256(
                json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            row["meta"] = _decode_json(row.get("meta_json"))
            rows.append(row)
        return {"count": len(rows), "rows": rows, "fingerprints": fingerprints}
    finally:
        connection.close()


def _validate_source_provenance(cfg: AppConfig, accepted_pack: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    verified = 0
    errors: list[dict[str, Any]] = []
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        for unit in accepted_pack:
            source = dict(unit.get("source") or {})
            document_id = unit.get("document_id") or source.get("document_id")
            chunk_id = unit.get("source_chunk_id") or source.get("chunk_id")
            cursor.execute(
                "SELECT c.id, c.doc_id, c.page_start, c.page_end, c.section_path, d.id AS document_exists "
                "FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE c.id=%s AND c.doc_id=%s LIMIT 1",
                (chunk_id, document_id),
            )
            row = cursor.fetchone()
            if not row:
                errors.append(
                    {
                        "candidate_id": unit.get("candidate_id"),
                        "type": "source_provenance_missing",
                        "document_id": document_id,
                        "chunk_id": chunk_id,
                    }
                )
                continue
            page_no = source.get("page_no")
            if page_no not in (None, row.get("page_start"), row.get("page_end")):
                errors.append(
                    {
                        "candidate_id": unit.get("candidate_id"),
                        "type": "source_page_mismatch",
                        "expected": page_no,
                        "actual": [row.get("page_start"), row.get("page_end")],
                    }
                )
                continue
            verified += 1
        return verified, errors
    finally:
        connection.close()


def build_write_dry_run(cfg: AppConfig, accepted_pack: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot = fetch_database_snapshot(cfg)
    plans = [map_candidate_to_write_plan(unit) for unit in accepted_pack]
    preflight = preflight_validate_write_plan(plans)
    blocking_errors: list[dict[str, Any]] = []
    for plan in plans:
        blocking_errors.extend(dict(item) for item in plan.get("blocking_errors") or [])

    candidate_ids = [str(unit.get("candidate_id") or "") for unit in accepted_pack]
    candidate_hashes = [str(unit.get("candidate_hash") or "") for unit in accepted_pack]
    dedup_keys = [str(unit.get("dedup_key") or "") for unit in accepted_pack]
    for label, values in (
        ("candidate_id", candidate_ids),
        ("candidate_hash", candidate_hashes),
        ("dedup_key", dedup_keys),
    ):
        if not all(values) or len(set(values)) != len(values):
            blocking_errors.append({"type": f"non_unique_{label}", "message": f"{label} values must be non-empty and unique"})

    verified_count, provenance_errors = _validate_source_provenance(cfg, accepted_pack)
    blocking_errors.extend(provenance_errors)

    existing_codes = set(snapshot.get("unit_codes") or set())
    existing_keys = set(snapshot.get("unit_keys") or set())
    new_plans: list[dict[str, Any]] = []
    skipped_existing: list[dict[str, Any]] = []
    for plan in plans:
        if str(plan.get("unit_code") or "") in existing_codes or str(plan.get("dedup_key") or "") in existing_keys:
            skipped_existing.append(
                {
                    "candidate_id": plan.get("candidate_id"),
                    "unit_code": plan.get("unit_code"),
                    "dedup_key": plan.get("dedup_key"),
                    "reason": "existing_unit_identity",
                }
            )
        else:
            new_plans.append(plan)

    writer_dry_run = write_knowledge_units_transactional(new_plans, write_db=False)
    writer_blocked = int(writer_dry_run.get("preflight", {}).get("blocked_count") or 0)
    if writer_blocked:
        blocking_errors.append({"type": "writer_preflight_blocked", "count": writer_blocked})

    return {
        "status": "ready" if not blocking_errors else "blocked",
        "database_target": f"{cfg.mysql.host}:{cfg.mysql.port}/{cfg.mysql.database}",
        "password_logged": False,
        "knowledge_units_before": int(snapshot.get("table_counts", {}).get("knowledge_units") or 0),
        "accepted_pack_count": len(accepted_pack),
        "mapped_plan_count": len(plans),
        "planned_new_inserts": len(new_plans),
        "planned_updates": 0,
        "planned_skips_existing": len(skipped_existing),
        "skipped_existing": skipped_existing,
        "duplicate_insert_attempts": 0,
        "source_provenance_verified_count": verified_count,
        "preflight": preflight,
        "writer_dry_run": writer_dry_run,
        "blocking_error_count": len(blocking_errors),
        "blocking_errors": blocking_errors,
        "new_plans": new_plans,
        "main_index_update_planned": False,
        "retrieval_main_path_change_planned": False,
        "schema_change_planned": False,
    }


def execute_write(cfg: AppConfig, accepted_pack: list[dict[str, Any]]) -> dict[str, Any]:
    dry_run = build_write_dry_run(cfg, accepted_pack)
    if dry_run["blocking_error_count"]:
        return {
            "status": "blocked",
            "database_written": False,
            "blocking_errors": dry_run["blocking_errors"],
            "dry_run": dry_run,
        }
    plans = list(dry_run.get("new_plans") or [])
    if not plans:
        return {
            "status": "already_applied",
            "database_written": False,
            "inserted_count": 0,
            "updated_count": 0,
            "skipped_existing_count": dry_run["planned_skips_existing"],
            "dry_run": dry_run,
        }
    result = write_knowledge_units_transactional(plans, write_db=True)
    result["skipped_existing_count"] = dry_run["planned_skips_existing"]
    result["dry_run"] = dry_run
    return result


def stamp_accepted_pack(accepted_pack: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in accepted_pack:
        item = dict(raw)
        item["source_run_name"] = run_id
        properties = dict(item.get("properties") or {})
        properties["review_run_id"] = run_id
        item["properties"] = properties
        output.append(item)
    return output


def readback_accepted_units(
    cfg: AppConfig,
    accepted_pack: list[dict[str, Any]],
    *,
    before_snapshot: dict[str, Any],
) -> dict[str, Any]:
    plans = [map_candidate_to_write_plan(item) for item in accepted_pack]
    expected_by_code = {str(plan.get("unit_code")): plan for plan in plans}
    source_by_code = {
        str(plan.get("unit_code")): dict(unit.get("source") or {})
        for unit, plan in zip(accepted_pack, plans)
    }
    found_by_code: dict[str, dict[str, Any]] = {}
    provenance_match_count = 0
    field_match_count = 0
    source_page_match_count = 0
    source_section_match_count = 0
    source_section_unavailable_count = 0
    source_locator_match_count = 0
    mismatches: list[dict[str, Any]] = []
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        codes = list(expected_by_code)
        if codes:
            placeholders = ",".join(["%s"] * len(codes))
            cursor.execute(
                "SELECT id, unit_code, unit_type, title, summary, content, source_doc_id, source_chunk_id, "
                f"page_start, page_end, meta_json FROM knowledge_units WHERE unit_code IN ({placeholders}) ORDER BY id",
                tuple(codes),
            )
            for row in cursor.fetchall() or []:
                item = dict(row)
                item["meta"] = _decode_json(item.get("meta_json"))
                found_by_code[str(item.get("unit_code"))] = item

        for code, plan in expected_by_code.items():
            row = found_by_code.get(code)
            if not row:
                continue
            expected = {
                "unit_type": plan.get("unit_type"),
                "title": plan.get("title"),
                "content": plan.get("content"),
                "source_doc_id": int(plan.get("document_id")) if plan.get("document_id") is not None else None,
                "source_chunk_id": int(plan.get("source_chunk_id")) if plan.get("source_chunk_id") is not None else None,
            }
            actual = {key: row.get(key) for key in expected}
            field_differences = {
                key: {"expected": value, "actual": actual.get(key)}
                for key, value in expected.items()
                if value != actual.get(key)
            }
            if field_differences:
                mismatches.append({"unit_code": code, "fields": field_differences})
            else:
                field_match_count += 1
            meta = dict(row.get("meta") or {})
            if (
                row.get("source_doc_id") == expected["source_doc_id"]
                and row.get("source_chunk_id") == expected["source_chunk_id"]
                and str(meta.get("dedup_key") or "") == str(plan.get("dedup_key") or "")
            ):
                provenance_match_count += 1
            cursor.execute(
                "SELECT page_start, page_end, section_path FROM chunks WHERE id=%s AND doc_id=%s LIMIT 1",
                (row.get("source_chunk_id"), row.get("source_doc_id")),
            )
            chunk_locator = cursor.fetchone() or {}
            expected_source = source_by_code.get(code) or {}
            expected_page = expected_source.get("page_no")
            page_match = expected_page in (chunk_locator.get("page_start"), chunk_locator.get("page_end"))
            if page_match:
                source_page_match_count += 1
            expected_section = str(expected_source.get("section_title") or "").strip()
            actual_section = str(chunk_locator.get("section_path") or "").strip()
            section_match = bool(expected_section and actual_section and expected_section == actual_section)
            if section_match:
                source_section_match_count += 1
            elif expected_section and not actual_section:
                source_section_unavailable_count += 1
            if page_match or section_match:
                source_locator_match_count += 1
    finally:
        connection.close()

    after_snapshot = knowledge_unit_snapshot(cfg)
    old_fingerprints = dict(before_snapshot.get("fingerprints") or {})
    new_fingerprints = dict(after_snapshot.get("fingerprints") or {})
    old_modified = [code for code, digest in old_fingerprints.items() if new_fingerprints.get(code) != digest]
    missing_codes = sorted(set(expected_by_code) - set(found_by_code))
    return {
        "expected_accepted_units": len(expected_by_code),
        "found_units": len(found_by_code),
        "missing_units": missing_codes,
        "field_match_count": field_match_count,
        "field_mismatch_count": len(mismatches),
        "field_mismatches": mismatches,
        "provenance_match_count": provenance_match_count,
        "source_page_match_count": source_page_match_count,
        "source_section_match_count": source_section_match_count,
        "source_section_unavailable_count": source_section_unavailable_count,
        "source_locator_match_count": source_locator_match_count,
        "source_document_match_count": sum(
            found_by_code[code].get("source_doc_id") == plan.get("document_id")
            for code, plan in expected_by_code.items()
            if code in found_by_code
        ),
        "source_chunk_match_count": sum(
            found_by_code[code].get("source_chunk_id") == plan.get("source_chunk_id")
            for code, plan in expected_by_code.items()
            if code in found_by_code
        ),
        "unit_type_match_count": sum(
            found_by_code[code].get("unit_type") == plan.get("unit_type")
            for code, plan in expected_by_code.items()
            if code in found_by_code
        ),
        "old_knowledge_units_count": int(before_snapshot.get("count") or 0),
        "new_knowledge_units_count": max(0, int(after_snapshot.get("count") or 0) - int(before_snapshot.get("count") or 0)),
        "final_knowledge_units_count": int(after_snapshot.get("count") or 0),
        "old_units_preserved_count": len(old_fingerprints) - len(old_modified),
        "old_units_modified": old_modified,
        "old_10_still_present": int(before_snapshot.get("count") or 0) == 10 and not old_modified,
        "passed": (
            not missing_codes
            and not mismatches
            and provenance_match_count == len(expected_by_code)
            and source_locator_match_count == len(expected_by_code)
            and not old_modified
        ),
        "database_readback": True,
        "main_index_updated": False,
    }


def verify_idempotency(cfg: AppConfig, accepted_pack: list[dict[str, Any]]) -> dict[str, Any]:
    dry_run = build_write_dry_run(cfg, accepted_pack)
    return {
        "planned_new_inserts": dry_run.get("planned_new_inserts", 0),
        "skipped_existing": dry_run.get("planned_skips_existing", 0),
        "duplicate_insert_attempts": dry_run.get("duplicate_insert_attempts", 0),
        "blocking_error_count": dry_run.get("blocking_error_count", 0),
        "passed": (
            int(dry_run.get("planned_new_inserts") or 0) == 0
            and int(dry_run.get("planned_skips_existing") or 0) >= len(accepted_pack)
            and int(dry_run.get("duplicate_insert_attempts") or 0) == 0
        ),
        "dry_run": dry_run,
    }


NEW_QUERY_TEXT = {
    "frontier_htw_parallel_subloop": "How are the active and reserve HTW branches arranged at Frontier?",
    "frontier_cascaded_cooling_loops": "Trace processor heat through the glycol, hot-water, and cooling-tower loops.",
    "frontier_htw_operating_flow_range": "What facility-level HTW mass-flow range is reported for Frontier?",
    "frontier_active_htw_subloop_components": "Which components are contained in each active HTW branch?",
    "frontier_variable_speed_htw_pump": "What does the variable-speed pump do in the Frontier hot-water circuit?",
    "frontier_constant_effectiveness_heat_exchanger": "Which constant-effectiveness equation relates exchanger heat transfer to inlet temperatures?",
    "frontier_htw_ua_flow_scaling": "How does the study scale exchanger UA with HTW mass flow?",
    "frontier_htw_pump_power_scaling": "How is variable-speed pump power scaled with flow in the digital twin?",
    "frontier_cooling_tower_heat_rejection_balance": "What energy balance gives cooling-tower rejected heat for three active branches?",
    "frontier_total_cooling_power_balance": "Which loads are added to obtain modeled total cooling power?",
    "frontier_dataset_internal_specific_heat": "Why would validating with the dataset's 3709 J per kg K constant be circular?",
    "frontier_digital_twin_adopted_specific_heat": "Which coolant specific heat did the Frontier validation model adopt, and over what temperature range?",
    "frontier_strategy_c_supply_temperature_range": "What supply-temperature window did Strategy C use in the July-week simulation?",
    "frontier_return_temperature_cv_rmse": "What return-temperature CV-RMSE range was reported for the calibrated digital twin?",
    "intel_xeon_multidie_tcase_compliance": "How does workload affect CPU-die and Fabric-die TCASE compliance on the covered Xeon platform?",
    "intel_xeon_case_to_ambient_psi_ca": "How is the Xeon case-to-local-ambient thermal characterization parameter calculated?",
    "intel_xeon_psi_ca_decomposition": "How is Psi CA split into TIM and heatsink-to-ambient contributions?",
    "coursework_cold_plate_aluminum_specific_heat": "What aluminum specific heat was entered for the three coursework cold plates?",
    "coursework_cold_plate_aluminum_density": "What aluminum density was entered in the cold-plate simulation assignment?",
    "coursework_air_dynamic_viscosity": "Which air viscosity was used at 20 C and standard pressure in the coursework model?",
    "coursework_cold_plate_aluminum_thermal_conductivity": "What thermal conductivity was assigned to the modeled aluminum cold plates?",
    "coursework_cold_plate_pressure_loss_definition": "How does the coursework define cold-plate pressure loss?",
}


def build_new_shadow_queries(accepted_pack: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for index, unit in enumerate(accepted_pack, start=1):
        canonical = str(unit.get("canonical_name") or "")
        keywords = [str(item) for item in unit.get("keywords") or [] if str(item).strip()]
        queries.append(
            {
                "query_id": f"external_review_{index:02d}",
                "query": NEW_QUERY_TEXT.get(canonical, " ".join(keywords[:3])),
                "category": "external_source_review",
                "difficulty": "medium",
                "expected_unit_types": [unit.get("unit_type")],
                "expected_keywords": keywords[:4] or [canonical],
                "expected_canonical_names": [canonical],
            }
        )
    return queries


def run_shadow_baseline(cfg: AppConfig, query_path: str | Path) -> dict[str, Any]:
    specs = load_shadow_query_set(query_path)
    payload = run_shadow_evaluation(
        specs,
        adapter=KnowledgeUnitsRetrievalAdapter(cfg=cfg, enabled=True),
        top_k=3,
    )
    payload.update(
        {
            "sample_limited": True,
            "production_ready": False,
            "main_index_updated": False,
            "retrieval_main_path_changed": False,
        }
    )
    return payload


def run_shadow_after(
    cfg: AppConfig,
    query_path: str | Path,
    accepted_pack: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    old_specs = load_shadow_query_set(query_path)
    new_specs = build_new_shadow_queries(accepted_pack)
    adapter = KnowledgeUnitsRetrievalAdapter(cfg=cfg, enabled=True)
    old_after = run_shadow_evaluation(old_specs, adapter=adapter, top_k=3)
    new_after = run_shadow_evaluation(new_specs, adapter=adapter, top_k=3)
    combined = run_shadow_evaluation(old_specs + new_specs, adapter=adapter, top_k=3)
    combined.update(
        {
            "old_query_count": len(old_specs),
            "new_unit_query_count": len(new_specs),
            "new_unit_evaluation": new_after,
            "old_query_evaluation": old_after,
            "recall_at_1": new_after.get("precision_at_1", 0.0),
            "recall_at_3": round(
                sum(bool(item.get("has_relevant_hit")) for item in new_after.get("query_results") or []) / len(new_specs),
                4,
            ) if new_specs else 0.0,
            "new_unit_hit_rate": round(
                sum(bool(item.get("has_relevant_hit")) for item in new_after.get("query_results") or []) / len(new_specs),
                4,
            ) if new_specs else 0.0,
            "false_positive_count": int(combined.get("wrong_hit_count") or 0),
            "sample_limited": True,
            "production_ready": False,
            "main_index_updated": False,
            "retrieval_main_path_changed": False,
        }
    )
    return combined, {"old_specs": old_specs, "new_specs": new_specs}


def compare_shadow(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_rows = {str(item.get("query_id")): item for item in before.get("query_results") or []}
    after_old = dict(after.get("old_query_evaluation") or {})
    after_rows = {str(item.get("query_id")): item for item in after_old.get("query_results") or []}
    regressions = [
        query_id
        for query_id, row in before_rows.items()
        if bool(row.get("has_relevant_hit")) and not bool(after_rows.get(query_id, {}).get("has_relevant_hit"))
    ]
    denominator = max(1, len(before_rows))
    return {
        "before": {
            key: before.get(key)
            for key in ("query_count", "precision_at_1", "precision_at_3", "unit_type_match_rate", "provenance_ready_rate")
        },
        "after": {
            key: after.get(key)
            for key in ("query_count", "precision_at_1", "precision_at_3", "unit_type_match_rate", "provenance_ready_rate", "recall_at_1", "recall_at_3", "new_unit_hit_rate", "false_positive_count")
        },
        "old_query_regressions": regressions,
        "old_query_regression_rate": round(len(regressions) / denominator, 4),
        "old_query_preservation_rate": round(1.0 - len(regressions) / denominator, 4),
        "new_unit_hit_rate": after.get("new_unit_hit_rate", 0.0),
        "provenance_ready_not_decreased": float(after.get("provenance_ready_rate") or 0.0) >= float(before.get("provenance_ready_rate") or 0.0),
        "sample_limited": True,
        "production_ready": False,
        "main_index_updated": False,
        "retrieval_main_path_changed": False,
    }


def build_review_summary_markdown(summary: dict[str, Any]) -> str:
    counts = summary.get("decision_counts") or {}
    return "\n".join(
        [
            "# External Knowledge Unit Source-Grounded Review",
            "",
            f"- Input candidates: {summary.get('input_candidates', 0)}",
            f"- Reviewed candidates: {summary.get('reviewed_candidates', 0)}",
            f"- Accepted candidate decisions: {counts.get('accepted', 0)}",
            f"- Accepted knowledge units after splits: {len(summary.get('accepted_pack') or [])}",
            f"- Duplicate: {counts.get('duplicate', 0)}",
            f"- Rejected: {counts.get('rejected', 0)}",
            f"- Still needs human review: {counts.get('still_needs_human_review', 0)}",
            f"- Repaired: {summary.get('repaired_count', 0)}",
            f"- Split additions: {summary.get('split_count', 0)}",
            f"- Provenance verified: {summary.get('provenance_verified_count', 0)}",
            f"- Reviewer type: {summary.get('reviewer_type')}",
            "- Human reviewed: false",
            "- Human review faked: false",
            "- External model/API used: false",
            "- Main index updated: false",
        ]
    ) + "\n"


def build_write_markdown(payload: dict[str, Any], title: str) -> str:
    lines = [f"# {title}", ""]
    for key in (
        "status", "knowledge_units_before", "accepted_pack_count", "planned_new_inserts",
        "planned_updates", "planned_skips_existing", "blocking_error_count", "inserted_count",
        "updated_count", "skipped_existing_count", "committed", "rolled_back",
    ):
        if key in payload:
            lines.append(f"- {key}: {payload.get(key)}")
    lines.extend(
        [
            "- Database password logged: false",
            "- Schema changed: false",
            "- Main index updated: false",
            "- Main retrieval path changed: false",
        ]
    )
    return "\n".join(lines) + "\n"


def build_readback_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# External Knowledge Unit Readback",
            "",
            f"- Passed: {payload.get('passed')}",
            f"- Expected: {payload.get('expected_accepted_units')}",
            f"- Found: {payload.get('found_units')}",
            f"- Missing: {len(payload.get('missing_units') or [])}",
            f"- Field matches: {payload.get('field_match_count')}",
            f"- Field mismatches: {payload.get('field_mismatch_count')}",
            f"- Provenance matches: {payload.get('provenance_match_count')}",
            f"- Source page matches: {payload.get('source_page_match_count')}",
            f"- Source section matches: {payload.get('source_section_match_count')}",
            f"- Source section unavailable: {payload.get('source_section_unavailable_count')}",
            f"- Source locator matches: {payload.get('source_locator_match_count')}",
            f"- Old KU count: {payload.get('old_knowledge_units_count')}",
            f"- New KU count: {payload.get('new_knowledge_units_count')}",
            f"- Final KU count: {payload.get('final_knowledge_units_count')}",
            f"- Old 10 still present and unchanged: {payload.get('old_10_still_present')}",
            "- Database readback: true",
            "- Main index updated: false",
        ]
    ) + "\n"


def build_shadow_comparison_markdown(payload: dict[str, Any]) -> str:
    before = payload.get("before") or {}
    after = payload.get("after") or {}
    return "\n".join(
        [
            "# External KU Shadow Retrieval Before/After",
            "",
            f"- Before P@1: {before.get('precision_at_1')}",
            f"- Before P@3: {before.get('precision_at_3')}",
            f"- After P@1: {after.get('precision_at_1')}",
            f"- After P@3: {after.get('precision_at_3')}",
            f"- After recall@1 (new queries): {after.get('recall_at_1')}",
            f"- After recall@3 (new queries): {after.get('recall_at_3')}",
            f"- Old query regression rate: {payload.get('old_query_regression_rate')}",
            f"- New unit hit rate: {payload.get('new_unit_hit_rate')}",
            f"- Provenance readiness not decreased: {payload.get('provenance_ready_not_decreased')}",
            "- Sample limited: true",
            "- Production ready claim: false",
            "- Main index updated: false",
            "- Main retrieval path changed: false",
        ]
    ) + "\n"
