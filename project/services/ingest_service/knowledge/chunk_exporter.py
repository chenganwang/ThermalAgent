from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SAMPLE_CHUNKS_JSON = Path("runtime") / "knowledge_unit_candidates" / "sample_chunks.json"
DEFAULT_SAMPLE_CANDIDATES_JSONL = Path("runtime") / "knowledge_unit_candidates" / "sample_knowledge_unit_candidates.jsonl"
DEFAULT_SAMPLE_REVIEW_SHEET = Path("runtime") / "knowledge_unit_candidates" / "sample_knowledge_unit_review_sheet.jsonl"
DEFAULT_SAMPLE_REVIEW_REPORT = Path("runtime") / "knowledge_unit_candidates" / "sample_knowledge_unit_review_report.md"
DEFAULT_RUNS_DIR = Path("runtime") / "knowledge_unit_candidates" / "runs"


def run_output_dir(run_name: str, base_dir: str | Path = DEFAULT_RUNS_DIR) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(run_name or "").strip())
    safe = safe.strip("._") or "run"
    return Path(base_dir) / safe


def sample_output_paths_for_run(run_name: str, base_dir: str | Path = DEFAULT_RUNS_DIR) -> dict[str, Path]:
    root = run_output_dir(run_name, base_dir)
    return {
        "run_dir": root,
        "chunks": root / "sample_chunks.json",
        "candidates": root / "sample_knowledge_unit_candidates.jsonl",
        "review_sheet": root / "sample_knowledge_unit_review_sheet.jsonl",
        "review_report": root / "sample_knowledge_unit_review_report.md",
    }


class _ConnectionAdapter:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple]:
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())

    def close(self) -> None:
        self.conn.close()


def _connect_readonly() -> tuple[Any | None, list[str]]:
    warnings: list[str] = []
    try:
        from mysql.connector import connect  # type: ignore
    except Exception as exc:
        return None, [f"mysql_connector_unavailable:{type(exc).__name__}"]
    try:
        from services.retrieval_service.config import load_config

        cfg = load_config()
        conn = connect(
            host=cfg.mysql.host,
            port=cfg.mysql.port,
            user=cfg.mysql.user,
            password=cfg.mysql.password,
            database=cfg.mysql.database,
            autocommit=True,
        )
        return _ConnectionAdapter(conn), warnings
    except Exception as exc:
        return None, [f"db_unavailable:{type(exc).__name__}"]


def _row_to_chunk(row: tuple, *, joined: bool) -> dict[str, Any]:
    if joined:
        (
            chunk_id,
            doc_id,
            chunk_index,
            page_start,
            page_end,
            chunk_type,
            section_path,
            text,
            title,
            source_file,
        ) = row
    else:
        chunk_id, doc_id, chunk_index, page_start, page_end, chunk_type, section_path, text = row
        title = None
        source_file = None
    return {
        "document_id": doc_id,
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "page_no": page_start,
        "page_start": page_start,
        "page_end": page_end,
        "chunk_type": chunk_type or "text",
        "section_title": section_path,
        "source_file": source_file or title,
        "title": title,
        "text": text or "",
    }


def _clean_keywords(keyword: str | None = None, keywords: list[str] | tuple[str, ...] | None = None) -> list[str]:
    values: list[str] = []
    if keyword:
        values.append(str(keyword))
    for item in keywords or []:
        if item:
            values.append(str(item))
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _build_where(
    keyword: str | None,
    document_id: int | str | None,
    keywords: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["c.is_active=1", "c.text IS NOT NULL", "CHAR_LENGTH(c.text) > 0"]
    params: list[Any] = []
    clean_keywords = _clean_keywords(keyword, keywords)
    if clean_keywords:
        clauses.append("(" + " OR ".join("c.text LIKE %s" for _ in clean_keywords) + ")")
        params.extend(f"%{item}%" for item in clean_keywords)
    if document_id not in (None, ""):
        clauses.append("c.doc_id = %s")
        params.append(int(document_id))
    return " AND ".join(clauses), params


def export_sample_chunks(
    *,
    limit: int = 50,
    keyword: str | None = None,
    keywords: list[str] | tuple[str, ...] | None = None,
    document_id: int | str | None = None,
    db: Any | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    limit = max(0, int(limit or 0))
    if limit == 0:
        return [], ["limit_zero"]
    close_after = False
    if db is None:
        db, connect_warnings = _connect_readonly()
        warnings.extend(connect_warnings)
        close_after = db is not None
    if db is None:
        return [], warnings

    where_sql, params = _build_where(keyword, document_id, keywords)
    params.append(limit)
    joined_sql = f"""
        SELECT c.id, c.doc_id, c.chunk_index, c.page_start, c.page_end,
               c.chunk_type, c.section_path, c.text, d.title, d.source
        FROM chunks c
        LEFT JOIN documents d ON d.id = c.doc_id
        WHERE {where_sql}
        ORDER BY c.id ASC
        LIMIT %s
    """
    simple_sql = f"""
        SELECT c.id, c.doc_id, c.chunk_index, c.page_start, c.page_end,
               c.chunk_type, c.section_path, c.text
        FROM chunks c
        WHERE {where_sql}
        ORDER BY c.id ASC
        LIMIT %s
    """
    try:
        try:
            rows = db.fetchall(joined_sql, tuple(params))
            chunks = [_row_to_chunk(row, joined=True) for row in rows]
        except Exception as exc:
            warnings.append(f"joined_chunk_query_failed:{type(exc).__name__}")
            rows = db.fetchall(simple_sql, tuple(params))
            chunks = [_row_to_chunk(row, joined=False) for row in rows]
        return chunks, warnings
    except Exception as exc:
        warnings.append(f"sample_chunk_export_failed:{type(exc).__name__}")
        return [], warnings
    finally:
        if close_after and hasattr(db, "close"):
            try:
                db.close()
            except Exception:
                pass


def write_sample_chunks_json(chunks: list[dict[str, Any]], path: str | Path, warnings: list[str] | None = None) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "chunks": list(chunks or []),
        "warnings": list(warnings or []),
        "database_written": False,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
