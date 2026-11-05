from __future__ import annotations
import argparse
import json
from pathlib import Path

from services.retrieval_service.config import load_config
from .ingest_docx_rich import ingest_docx
from .ingest_pdf_rich import ingest_pdf
from .knowledge.extractor import extract_knowledge_units_from_chunks
from .knowledge.report import DEFAULT_CANDIDATES_JSONL, DEFAULT_REPORT_MD, write_candidates_jsonl, write_extraction_report
from .knowledge.review import build_review_records, filter_candidates_by_review_status, load_candidates_jsonl_with_warnings, write_review_sheet
from .knowledge.review_report import DEFAULT_REVIEW_REPORT, DEFAULT_REVIEW_SHEET, write_review_report
from .knowledge.writer import DEFAULT_ACCEPTED_INPUT, build_writer_dry_run_from_path
from .knowledge.writer_report import DEFAULT_WRITER_REPORT_JSON, DEFAULT_WRITER_REPORT_MD, DEFAULT_WRITER_SQL_PREVIEW, write_writer_dry_run_outputs


def _load_chunks_json(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        chunks = payload
    elif isinstance(payload, dict):
        chunks = payload.get("chunks") or payload.get("items") or payload.get("data")
    else:
        chunks = None
    if not isinstance(chunks, list):
        raise SystemExit("--input-json must contain a JSON list or an object with a chunks/items/data list")
    return [item for item in chunks if isinstance(item, dict)]

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest service CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest")
    p_ing.add_argument("file")
    p_ing.add_argument("--force-ocr", action="store_true")
    p_ing.add_argument("--overwrite", action="store_true")

    p_extract = sub.add_parser("extract-knowledge", help="Dry-run knowledge unit candidate extraction from chunks JSON")
    p_extract.add_argument("--input-json", required=True, help="Path to chunks JSON")
    p_extract.add_argument("--output-jsonl", default=str(DEFAULT_CANDIDATES_JSONL), help="Candidate JSONL output path")
    p_extract.add_argument("--report-md", default=str(DEFAULT_REPORT_MD), help="Markdown report output path")
    p_extract.add_argument("--unit-types", nargs="*", default=None, help="Optional unit_type filter")
    p_extract.add_argument("--limit", type=int, default=None, help="Limit number of chunks for local dry-run checks")
    p_extract.add_argument("--dry-run", action="store_true", default=True, help="Default and only supported mode; does not write DB")

    p_review = sub.add_parser("review-knowledge", help="Build review sheet and quality report from candidates JSONL")
    p_review.add_argument("--input", default=str(DEFAULT_CANDIDATES_JSONL), help="Input candidates JSONL or review sheet JSONL")
    p_review.add_argument("--output-sheet", default=str(DEFAULT_REVIEW_SHEET), help="Review sheet JSONL output path")
    p_review.add_argument("--output-report", default=str(DEFAULT_REVIEW_REPORT), help="Review report Markdown output path")
    p_review.add_argument("--min-quality-score", type=float, default=None, help="Optional minimum quality score filter")
    p_review.add_argument("--only-status", default=None, help="Comma-separated review_status filter")

    p_write = sub.add_parser("write-knowledge-dry-run", help="Build MySQL upsert preview for accepted knowledge units without DB writes")
    p_write.add_argument("--input", default=str(DEFAULT_ACCEPTED_INPUT), help="Accepted candidates JSONL input")
    p_write.add_argument("--report-md", default=str(DEFAULT_WRITER_REPORT_MD), help="Markdown dry-run report output path")
    p_write.add_argument("--report-json", default=str(DEFAULT_WRITER_REPORT_JSON), help="JSON dry-run report output path")
    p_write.add_argument("--sql-preview", default=str(DEFAULT_WRITER_SQL_PREVIEW), help="Commented SQL preview output path")

    args = parser.parse_args()
    if args.cmd == "extract-knowledge":
        chunks = _load_chunks_json(Path(args.input_json))
        if args.limit is not None:
            chunks = chunks[: max(0, int(args.limit))]
        candidates = extract_knowledge_units_from_chunks(chunks)
        if args.unit_types:
            allowed = {str(unit_type) for unit_type in args.unit_types}
            candidates = [candidate for candidate in candidates if candidate.unit_type in allowed]
        jsonl_path = write_candidates_jsonl(candidates, args.output_jsonl)
        report_path = write_extraction_report(candidates, args.report_md)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "dry_run": True,
                    "chunks_read": len(chunks),
                    "candidates": len(candidates),
                    "output_jsonl": str(jsonl_path),
                    "report_md": str(report_path),
                    "database_written": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.cmd == "review-knowledge":
        raw_records, warnings = load_candidates_jsonl_with_warnings(args.input)
        if raw_records and all("candidate_id" in item and "quality_score" in item for item in raw_records):
            records = raw_records
        else:
            records = build_review_records(raw_records)
        if args.min_quality_score is not None:
            records = [record for record in records if float(record.get("quality_score") or 0.0) >= float(args.min_quality_score)]
        if args.only_status:
            statuses = [item.strip() for item in args.only_status.split(",") if item.strip()]
            records = filter_candidates_by_review_status(records, statuses)
        sheet_path = write_review_sheet(records, args.output_sheet)
        report_path = write_review_report(records, args.output_report)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "records": len(records),
                    "output_sheet": str(sheet_path),
                    "output_report": str(report_path),
                    "warnings": warnings,
                    "database_written": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.cmd == "write-knowledge-dry-run":
        result = build_writer_dry_run_from_path(args.input)
        outputs = write_writer_dry_run_outputs(
            result,
            report_md=args.report_md,
            report_json=args.report_json,
            sql_preview=args.sql_preview,
        )
        print(
            json.dumps(
                {
                    "status": result.get("status"),
                    "input": str(Path(args.input)),
                    "total_candidates": result.get("total_candidates"),
                    "write_ready_count": result.get("write_ready_count"),
                    "blocked_count": result.get("blocked_count"),
                    "counts_by_unit_type": result.get("counts_by_unit_type"),
                    "target_table_counts": result.get("target_table_counts"),
                    "duplicate_dedup_key_count": result.get("duplicate_dedup_key_count"),
                    "blocking_errors_by_type": result.get("blocking_errors_by_type"),
                    "warnings_by_type": result.get("warnings_by_type"),
                    "can_enter_phase2b": result.get("can_enter_phase2b"),
                    "dry_run_report": outputs["report_md"],
                    "dry_run_report_json": outputs["report_json"],
                    "sql_preview": outputs["sql_preview"],
                    "database_written": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    cfg = load_config()
    path = Path(args.file)
    if path.suffix.lower() == ".pdf":
        doc_id = ingest_pdf(path, cfg, force_ocr=args.force_ocr, overwrite=args.overwrite)
    elif path.suffix.lower() == ".docx":
        doc_id = ingest_docx(path, cfg, overwrite=args.overwrite)
    else:
        raise SystemExit(f"unsupported file type: {path.suffix}")
    print(f"Ingested doc_id={doc_id}")

if __name__ == "__main__":
    main()
