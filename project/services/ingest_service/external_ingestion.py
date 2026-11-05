from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from services.ingest_service.db_schema_compat import (
    get_or_create_document_compat,
    insert_chunks_compat,
    sync_document_sections_for_doc,
)
from services.ingest_service.external_sources import (
    build_external_ingestion_dry_run,
    build_external_source_inventory,
    compare_external_ingestion_readback,
    gate_external_knowledge_candidates,
    inspect_and_score_inventory,
    parse_external_source,
    select_external_sources,
)
from services.ingest_service.knowledge.db_writer import write_knowledge_units_transactional
from services.ingest_service.knowledge.extractor import extract_knowledge_units_from_chunks
from services.ingest_service.knowledge.quality import score_candidate_quality
from services.ingest_service.knowledge.writer_mapping import map_candidate_to_write_plan
from services.retrieval_service.config import AppConfig


COUNTED_TABLES = (
    "source_assets", "documents", "chunks", "knowledge_units", "formulas", "components",
    "thermal_paths", "fault_cases", "experiment_logs", "evaluation_runs",
)


def utc_run_id() -> str:
    return "external_ingestion_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def write_json(path: str | Path, payload: Any) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    return output


def connect_mysql(cfg: AppConfig, *, autocommit: bool = False) -> Any:
    import mysql.connector

    return mysql.connector.connect(
        host=cfg.mysql.host,
        port=cfg.mysql.port,
        user=cfg.mysql.user,
        password=cfg.mysql.password,
        database=cfg.mysql.database,
        autocommit=autocommit,
        charset="utf8mb4",
        use_unicode=True,
    )


def _decode_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def fetch_database_snapshot(cfg: AppConfig) -> dict[str, Any]:
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        table_counts: dict[str, int | None] = {}
        for table in COUNTED_TABLES:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s",
                (table,),
            )
            exists = int((cursor.fetchone() or {}).get("n") or 0) > 0
            if not exists:
                table_counts[table] = None
                continue
            cursor.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
            table_counts[table] = int((cursor.fetchone() or {}).get("n") or 0)

        cursor.execute("SELECT id, source, title, sha256, local_path, meta_json FROM documents ORDER BY id")
        documents = list(cursor.fetchall() or [])
        cursor.execute("SELECT id, doc_id, chunk_id, asset_type, title, file_path, asset_meta FROM source_assets ORDER BY id")
        source_assets = list(cursor.fetchall() or [])
        cursor.execute("SELECT id, unit_code, source_doc_id, source_chunk_id, meta_json FROM knowledge_units ORDER BY id")
        units = list(cursor.fetchall() or [])
        unit_keys: set[str] = set()
        unit_codes: set[str] = set()
        for unit in units:
            code = str(unit.get("unit_code") or "").strip()
            if code:
                unit_codes.add(code)
            key = str(_decode_json(unit.get("meta_json")).get("dedup_key") or "").strip()
            if key:
                unit_keys.add(key)
        return {
            "table_counts": table_counts,
            "documents": documents,
            "source_assets": source_assets,
            "knowledge_units": units,
            "document_hashes": {str(item.get("sha256") or "").lower() for item in documents if item.get("sha256")},
            "unit_keys": unit_keys,
            "unit_codes": unit_codes,
        }
    finally:
        connection.close()


def parse_selected_sources(selected: list[dict[str, Any]], cfg: AppConfig, *, run_id: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    parsed: dict[str, dict[str, Any]] = {}
    summaries: list[dict[str, Any]] = []
    for item in selected:
        digest = str(item.get("sha256") or "").lower()
        try:
            result = parse_external_source(item["absolute_path"], cfg, run_id=run_id)
        except Exception as exc:
            result = {
                "status": "parse_failed",
                "quality_passed": False,
                "chunk_count": 0,
                "rows": [],
                "error": f"{type(exc).__name__}:{exc}",
            }
        parsed[digest] = result
        summaries.append(
            {
                "relative_path": item.get("relative_path"),
                "sha256": digest,
                "status": result.get("status"),
                "quality_passed": bool(result.get("quality_passed")),
                "parser": result.get("parser"),
                "page_count": result.get("page_count"),
                "character_count": result.get("character_count", 0),
                "chunk_count": result.get("chunk_count", 0),
                "empty_chunk_count": result.get("empty_chunk_count", 0),
                "garbled_ratio": result.get("garbled_ratio"),
                "error": result.get("error"),
            }
        )
    return parsed, summaries


def _candidate_chunks(
    selected: list[dict[str, Any]],
    parsed: dict[str, dict[str, Any]],
    *,
    provenance: dict[str, dict[int, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for item in selected:
        digest = str(item.get("sha256") or "").lower()
        result = parsed.get(digest) or {}
        if not result.get("quality_passed"):
            continue
        source_map = (provenance or {}).get(digest) or {}
        for row in result.get("rows") or []:
            linked = source_map.get(int(row.chunk_index)) or {}
            chunks.append(
                {
                    "id": linked.get("chunk_id") or f"planned:{digest}:{row.chunk_index}",
                    "doc_id": linked.get("document_id") or f"planned:{digest}",
                    "chunk_index": row.chunk_index,
                    "page_start": row.page_start,
                    "page_end": row.page_end,
                    "chunk_type": row.chunk_type,
                    "section_path": row.section_path,
                    "text": row.text,
                    "meta_json": {
                        **(dict(row.meta_json) if isinstance(row.meta_json, dict) else {}),
                        "source_file": item.get("filename"),
                    },
                }
            )
    return chunks


def generate_and_gate_candidates(
    selected: list[dict[str, Any]],
    parsed: dict[str, dict[str, Any]],
    *,
    existing_unit_keys: set[str],
    provenance: dict[str, dict[int, dict[str, Any]]] | None = None,
    source_asset_ids: dict[str, int] | None = None,
    run_id: str,
) -> dict[str, Any]:
    extracted = extract_knowledge_units_from_chunks(_candidate_chunks(selected, parsed, provenance=provenance))
    candidates: list[dict[str, Any]] = []
    for value in extracted:
        item = value.to_dict()
        quality = score_candidate_quality(item)
        item["quality_score"] = float(quality.get("quality_score") or 0.0)
        item["quality_flags"] = list(quality.get("quality_flags") or [])
        item["recommended_review_status"] = quality.get("recommended_review_status")
        item["source_run_name"] = run_id
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        document_id = source.get("document_id")
        digest = ""
        for source_digest, chunk_map in (provenance or {}).items():
            if any(link.get("document_id") == document_id for link in chunk_map.values()):
                digest = source_digest
                break
        if digest and source_asset_ids and digest in source_asset_ids:
            item["source_asset_id"] = source_asset_ids[digest]
        candidates.append(item)
    gate = gate_external_knowledge_candidates(candidates, existing_dedup_keys=existing_unit_keys)
    gate["candidate_count"] = len(candidates)
    return gate


class TransactionDB:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        return cursor

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> Any:
        cursor = self.connection.cursor()
        cursor.executemany(sql, params)
        return cursor

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        return cursor.fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        return list(cursor.fetchall() or [])


def write_selected_documents(
    selected: list[dict[str, Any]],
    parsed: dict[str, dict[str, Any]],
    cfg: AppConfig,
    *,
    run_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "inserted_documents": 0,
        "inserted_chunks": 0,
        "inserted_source_assets": 0,
        "skipped_existing_documents": 0,
        "failed_documents": [],
        "documents": [],
        "source_asset_ids": {},
        "provenance": {},
    }
    for item in selected:
        digest = str(item.get("sha256") or "").lower()
        parse_result = parsed.get(digest) or {}
        if not parse_result.get("quality_passed"):
            result["failed_documents"].append({"relative_path": item.get("relative_path"), "reason": "document_quality_gate_failed"})
            continue
        connection = connect_mysql(cfg, autocommit=False)
        try:
            if hasattr(connection, "start_transaction"):
                connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id FROM documents WHERE sha256=%s LIMIT 1", (digest,))
            existing = cursor.fetchone()
            if existing:
                document_id = int(existing["id"])
                result["skipped_existing_documents"] += 1
                cursor.execute(
                    "SELECT id FROM source_assets WHERE doc_id=%s AND asset_type=%s AND file_path=%s LIMIT 1",
                    (document_id, "document_source", str(item["absolute_path"])),
                )
                asset = cursor.fetchone()
                if asset:
                    result["source_asset_ids"][digest] = int(asset["id"])
                connection.rollback()
            else:
                db = TransactionDB(connection)
                document_id = get_or_create_document_compat(
                    db,
                    source=str(item["absolute_path"]),
                    title=str(parse_result.get("title") or Path(item["absolute_path"]).stem),
                    sha256=digest,
                    mime=parse_result.get("mime"),
                    doc_type="external_engineering_source",
                    language="zh-CN" if any("\u4e00" <= char <= "\u9fff" for char in str(parse_result.get("title") or "")) else "en",
                    local_path=str(item["absolute_path"]),
                    is_public=0,
                    license_note="Local source; usage rights not asserted by ingestion.",
                    meta_json={
                        "external_ingestion_run_id": run_id,
                        "source_sha256": digest,
                        "relative_path": item.get("relative_path"),
                        "main_index_update_skipped": True,
                    },
                )
                insert_chunks_compat(db, doc_id=document_id, rows=list(parse_result.get("rows") or []))
                sync_document_sections_for_doc(db, doc_id=document_id)
                raw_cursor = connection.cursor()
                raw_cursor.execute(
                    """
                    INSERT INTO source_assets
                        (doc_id, chunk_id, asset_type, title, description, file_path, page_number, asset_meta)
                    VALUES (%s, NULL, %s, %s, %s, %s, NULL, CAST(%s AS JSON))
                    """,
                    (
                        document_id,
                        "document_source",
                        item.get("filename"),
                        "External source selected by the idempotent ingestion workflow.",
                        str(item["absolute_path"]),
                        json.dumps({"sha256": digest, "run_id": run_id, "relative_path": item.get("relative_path")}, ensure_ascii=False),
                    ),
                )
                source_asset_id = int(raw_cursor.lastrowid)
                connection.commit()
                result["inserted_documents"] += 1
                result["inserted_chunks"] += int(parse_result.get("chunk_count") or 0)
                result["inserted_source_assets"] += 1
                result["source_asset_ids"][digest] = source_asset_id

            verify_cursor = connection.cursor(dictionary=True)
            verify_cursor.execute("SELECT id, chunk_index FROM chunks WHERE doc_id=%s ORDER BY chunk_index", (document_id,))
            links = {
                int(row["chunk_index"]): {"document_id": document_id, "chunk_id": int(row["id"])}
                for row in verify_cursor.fetchall() or []
            }
            result["provenance"][digest] = links
            result["documents"].append(
                {
                    "relative_path": item.get("relative_path"),
                    "sha256": digest,
                    "document_id": document_id,
                    "source_asset_id": result["source_asset_ids"].get(digest),
                    "chunk_count": len(links),
                    "status": "inserted" if not existing else "skipped_existing",
                }
            )
        except Exception as exc:
            connection.rollback()
            result["failed_documents"].append(
                {"relative_path": item.get("relative_path"), "reason": f"{type(exc).__name__}:{exc}"}
            )
        finally:
            connection.close()
    return result


def write_accepted_units(gate: dict[str, Any], existing_unit_codes: set[str]) -> dict[str, Any]:
    plans = []
    skipped = 0
    for candidate in gate.get("accepted") or []:
        plan = map_candidate_to_write_plan(candidate)
        if str(plan.get("unit_code") or "") in existing_unit_codes:
            skipped += 1
            continue
        plans.append(plan)
    if not plans:
        return {
            "status": "skipped_no_new_accepted_units",
            "total_candidates": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "skipped_existing_count": skipped,
            "database_written": False,
            "committed": False,
        }
    result = write_knowledge_units_transactional(plans, write_db=True, allow_missing_provenance=False)
    result["skipped_existing_count"] = skipped
    result["written_unit_keys"] = [str(plan.get("dedup_key")) for plan in plans] if result.get("committed") else []
    result["written_unit_codes"] = [str(plan.get("unit_code")) for plan in plans] if result.get("committed") else []
    return result


def readback_external_ingestion(
    cfg: AppConfig,
    selected: list[dict[str, Any]],
    *,
    expected_unit_keys: list[str],
) -> dict[str, Any]:
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        documents = []
        selected_doc_ids = []
        for item in selected:
            digest = str(item.get("sha256") or "").lower()
            cursor.execute("SELECT id, source, title, sha256, local_path, meta_json FROM documents WHERE sha256=%s LIMIT 1", (digest,))
            document = cursor.fetchone()
            if not document:
                continue
            doc_id = int(document["id"])
            selected_doc_ids.append(doc_id)
            cursor.execute(
                """
                SELECT COUNT(*) AS chunk_count,
                       SUM(CASE WHEN TRIM(text)='' THEN 1 ELSE 0 END) AS empty_chunks,
                       COUNT(*) - COUNT(DISTINCT COALESCE(content_hash, SHA2(text, 256))) AS duplicate_chunks
                FROM chunks WHERE doc_id=%s
                """,
                (doc_id,),
            )
            chunk_stats = cursor.fetchone() or {}
            cursor.execute("SELECT id, asset_type, file_path, asset_meta FROM source_assets WHERE doc_id=%s ORDER BY id", (doc_id,))
            assets = list(cursor.fetchall() or [])
            documents.append(
                {
                    "document_id": doc_id,
                    "sha256": digest,
                    "source": document.get("source"),
                    "local_path": document.get("local_path"),
                    "chunk_count": int(chunk_stats.get("chunk_count") or 0),
                    "empty_chunks": int(chunk_stats.get("empty_chunks") or 0),
                    "duplicate_chunks": int(chunk_stats.get("duplicate_chunks") or 0),
                    "source_assets": assets,
                    "source_hash_match": any(_decode_json(asset.get("asset_meta")).get("sha256") == digest for asset in assets),
                }
            )
        cursor.execute("SELECT COUNT(*) AS n FROM chunks c LEFT JOIN documents d ON d.id=c.doc_id WHERE d.id IS NULL")
        orphan_chunks = int((cursor.fetchone() or {}).get("n") or 0)

        units = []
        for key in expected_unit_keys:
            cursor.execute(
                "SELECT id, unit_code, unit_type, title, source_doc_id, source_chunk_id, page_start, page_end, meta_json FROM knowledge_units WHERE JSON_UNQUOTE(JSON_EXTRACT(meta_json, '$.dedup_key'))=%s LIMIT 1",
                (key,),
            )
            unit = cursor.fetchone()
            if not unit:
                continue
            meta = _decode_json(unit.get("meta_json"))
            source_doc_id = unit.get("source_doc_id")
            source_chunk_id = unit.get("source_chunk_id")
            cursor.execute("SELECT doc_id, page_start, page_end FROM chunks WHERE id=%s LIMIT 1", (source_chunk_id,))
            chunk = cursor.fetchone()
            units.append(
                {
                    "dedup_key": key,
                    "unit_code": unit.get("unit_code"),
                    "document_id": source_doc_id,
                    "source_chunk_id": source_chunk_id,
                    "provenance_match": bool(chunk and int(chunk.get("doc_id")) == int(source_doc_id)),
                    "source_page_match": bool(chunk and (unit.get("page_start") in (None, chunk.get("page_start")))),
                    "document_sha256": next((doc["sha256"] for doc in documents if doc["document_id"] == source_doc_id), None),
                    "meta": meta,
                }
            )
        return {"documents": documents, "knowledge_units": units, "orphan_chunks": orphan_chunks}
    finally:
        connection.close()


def _run_new_chunk_shadow_eval(cfg: AppConfig, documents: list[dict[str, Any]]) -> dict[str, Any]:
    query_templates = {
        "2603.01198v3.pdf": ["hot temperature water cooling loop", "data center liquid cooling optimization"],
        "xeon-scalable-thermal-guide.pdf": ["processor thermal management TCASE", "digital thermal sensor thermal profile"],
        "therm-gdlns-5th-r-e-refcard.pdf": ["ASHRAE equipment thermal guidelines", "A1 A4 humidity temperature classes"],
        "周雪.pdf": ["冷板 流道 散热", "冷板 压降"],
    }
    specs = []
    doc_ids = []
    for document in documents:
        doc_id = int(document.get("document_id") or 0)
        if not doc_id:
            continue
        doc_ids.append(doc_id)
        filename = Path(str(document.get("relative_path") or "")).name
        for query in query_templates.get(filename, []):
            specs.append({"query": query, "expected_document_id": doc_id, "filename": filename})
    if not specs or not doc_ids:
        return {"query_count": 0, "top_1_accuracy": 0.0, "top_3_accuracy": 0.0, "queries": [], "sample_limited": True}

    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        placeholders = ",".join(["%s"] * len(doc_ids))
        results = []
        for spec in specs:
            query = spec["query"]
            cursor.execute(
                f"""
                SELECT id, doc_id, page_start, section_path,
                       MATCH(text) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score
                FROM chunks
                WHERE doc_id IN ({placeholders})
                  AND MATCH(text) AGAINST (%s IN NATURAL LANGUAGE MODE)
                ORDER BY score DESC, id ASC
                LIMIT 3
                """,
                (query, *doc_ids, query),
            )
            hits = list(cursor.fetchall() or [])
            if not hits:
                terms = [term for term in query.split() if len(term) >= 2][:4]
                where = " OR ".join(["text LIKE %s"] * len(terms)) or "1=0"
                cursor.execute(
                    f"SELECT id, doc_id, page_start, section_path, 0.0 AS score FROM chunks WHERE doc_id IN ({placeholders}) AND ({where}) ORDER BY id ASC LIMIT 3",
                    (*doc_ids, *[f"%{term}%" for term in terms]),
                )
                hits = list(cursor.fetchall() or [])
            expected = int(spec["expected_document_id"])
            hit_doc_ids = [int(hit["doc_id"]) for hit in hits]
            results.append(
                {
                    **spec,
                    "top_1_match": bool(hit_doc_ids and hit_doc_ids[0] == expected),
                    "top_3_match": expected in hit_doc_ids[:3],
                    "hits": [
                        {"chunk_id": int(hit["id"]), "document_id": int(hit["doc_id"]), "page_start": hit.get("page_start"), "score": float(hit.get("score") or 0.0)}
                        for hit in hits
                    ],
                }
            )
        count = len(results)
        return {
            "query_count": count,
            "top_1_accuracy": round(sum(1 for item in results if item["top_1_match"]) / max(1, count), 4),
            "top_3_accuracy": round(sum(1 for item in results if item["top_3_match"]) / max(1, count), 4),
            "queries": results,
            "sample_limited": True,
        }
    finally:
        connection.close()


def run_external_shadow_evaluation(
    cfg: AppConfig,
    accepted: list[dict[str, Any]],
    *,
    new_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from services.retrieval_service.knowledge_units.adapter import KnowledgeUnitsRetrievalAdapter
    from services.retrieval_service.knowledge_units.evaluation import (
        DEFAULT_SHADOW_QUERY_SET,
        load_shadow_query_set,
        run_shadow_evaluation,
    )

    specs = load_shadow_query_set(DEFAULT_SHADOW_QUERY_SET) if Path(DEFAULT_SHADOW_QUERY_SET).exists() else []
    for index, candidate in enumerate(accepted[:10], start=1):
        canonical = str(candidate.get("canonical_name") or candidate.get("title") or "").strip()
        if not canonical:
            continue
        specs.append(
            {
                "query_id": f"external_{index:02d}",
                "query": f"{canonical} engineering definition or parameter",
                "category": "external_ingestion",
                "difficulty": "basic",
                "expected_unit_types": [candidate.get("unit_type")],
                "expected_keywords": [canonical],
                "expected_canonical_names": [canonical],
            }
        )
    adapter = KnowledgeUnitsRetrievalAdapter(cfg=cfg, enabled=True)
    evaluation = run_shadow_evaluation(specs, adapter=adapter, top_k=3, use_unit_type_filter=False)
    evaluation.update(
        {
            "sample_limited": len(accepted) < 10,
            "new_unit_query_count": min(len(accepted), 10),
            "old_knowledge_units_readable": int(fetch_database_snapshot(cfg)["table_counts"].get("knowledge_units") or 0) >= 10,
            "production_ready_claimed": False,
            "retrieval_main_path_changed": False,
            "new_chunks": _run_new_chunk_shadow_eval(cfg, new_documents or []),
        }
    )
    return evaluation


def build_selection_markdown(report: dict[str, Any], selected: list[dict[str, Any]]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# External Source Selection",
        "",
        f"- Scanned files: {summary.get('scanned_file_count', 0)}",
        f"- Hard-excluded backbone files: {summary.get('excluded_root_file_count', 0)}",
        f"- Already ingested files: {summary.get('already_ingested_file_count', 0)}",
        f"- Hash duplicates: {summary.get('hash_duplicate_file_count', 0)}",
        f"- OCR required (not run): {summary.get('ocr_required_count', 0)}",
        f"- Valid candidates: {summary.get('valid_candidate_count', 0)}",
        f"- Selected files: {len(selected)}",
        "- excluded_backbone_selected_count: 0",
        "",
        "## Selected",
        "",
        "| File | Score | Reason | Estimated chunks |",
        "|---|---:|---|---:|",
    ]
    for item in selected:
        lines.append(
            f"| {item.get('relative_path')} | {float(item.get('final_score') or 0):.4f} | {item.get('selection_reason')} | {item.get('estimated_chunks', 0)} |"
        )
    not_selected = sorted(
        [item for item in report.get("files") or [] if not item.get("excluded") and item.get("selection_status") != "selected"],
        key=lambda item: -float(item.get("final_score") or 0),
    )[:5]
    lines.extend(["", "## Highest-scoring not selected", ""])
    for item in not_selected:
        lines.append(f"- {item.get('relative_path')}: score={float(item.get('final_score') or 0):.4f}; capacity/priority cutoff")
    return "\n".join(lines) + "\n"


def build_readback_markdown(payload: dict[str, Any]) -> str:
    comparison = payload.get("comparison") or {}
    lines = [
        "# External Ingestion Readback",
        "",
        f"- Passed: {comparison.get('passed', False)}",
        f"- Documents found: {len(payload.get('documents') or [])}",
        f"- Knowledge units found: {len(payload.get('knowledge_units') or [])}",
        f"- Orphan chunks: {payload.get('orphan_chunks', 0)}",
        f"- Missing documents: {len(comparison.get('missing_documents') or [])}",
        f"- Missing knowledge units: {len(comparison.get('missing_knowledge_units') or [])}",
        f"- Provenance matches: {comparison.get('provenance_match_count', 0)}",
    ]
    return "\n".join(lines) + "\n"


def build_shadow_markdown(payload: dict[str, Any]) -> str:
    chunk_eval = payload.get("new_chunks") or {}
    lines = [
        "# External Ingestion Shadow Retrieval Evaluation",
        "",
        f"- Query count: {payload.get('query_count', 0)}",
        f"- Precision@1: {payload.get('precision_at_1', 0)}",
        f"- Precision@3: {payload.get('precision_at_3', 0)}",
        f"- Unit type match rate: {payload.get('unit_type_match_rate', 0)}",
        f"- Provenance ready rate: {payload.get('provenance_ready_rate', 0)}",
        f"- New-unit queries: {payload.get('new_unit_query_count', 0)}",
        f"- New-chunk queries: {chunk_eval.get('query_count', 0)}",
        f"- New-chunk top-1 accuracy: {chunk_eval.get('top_1_accuracy', 0)}",
        f"- New-chunk top-3 accuracy: {chunk_eval.get('top_3_accuracy', 0)}",
        f"- Old knowledge units readable: {payload.get('old_knowledge_units_readable', False)}",
        f"- Sample limited: {payload.get('sample_limited', True)}",
        "- Production-ready claim: false",
        "- Main retrieval path changed: false",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "build_readback_markdown",
    "build_selection_markdown",
    "build_shadow_markdown",
    "connect_mysql",
    "fetch_database_snapshot",
    "generate_and_gate_candidates",
    "json_default",
    "parse_selected_sources",
    "readback_external_ingestion",
    "run_external_shadow_evaluation",
    "utc_run_id",
    "write_accepted_units",
    "write_json",
    "write_selected_documents",
]
