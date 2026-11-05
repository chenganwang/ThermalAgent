from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from services.retrieval_service.config import AppConfig
from services.retrieval_service.db import DB
from .ocr_pdf import ocr_pdf_pages
from .chunking import build_chunk_context, chunk_blocks_to_rows
from .chunking.types import Block
from .rebuild_embeddings import rebuild_all
from .db_schema_compat import (
    count_chunks_for_doc_compat,
    delete_chunks_for_doc_compat,
    get_or_create_document_compat,
    insert_chunks_compat,
    sync_document_sections_for_doc,
)

logger = logging.getLogger(__name__)
PDF_MIME = "application/pdf"

_FRONT_MATTER_MARKERS = [
    "isbn", "copyright", "edition", "editor", "publisher", "preface", "foreword",
    "序", "序言", "前言", "修订", "再版", "出版说明", "编者", "作者简介", "内容简介", "教材说明",
]
_TOC_MARKERS = ["contents", "目录", "目 录"]
_FIGURE_CAPTION_RE = re.compile(r"^\s*(图|Figure)\s*[\dIVXivx]+([\-–\.]\d+)*\b")
_TABLE_CAPTION_RE = re.compile(r"^\s*(表|Table)\s*[\dIVXivx]+([\-–\.]\d+)*\b")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _normalize_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_paragraphs(text: str) -> list[str]:
    t = _normalize_text(text)
    parts = []
    for raw in re.split(r"\n{2,}", t):
        s = raw.strip()
        if s:
            parts.append(s)
    if not parts and t.strip():
        parts = [t.strip()]
    return parts


def _looks_like_front_matter_page(text: str, page_no: int, cfg: AppConfig) -> bool:
    t = _normalize_text(text)
    if not t:
        return True
    cleanup = cfg.pdf_cleanup
    if cleanup.drop_first_pages and page_no <= int(cleanup.drop_first_pages):
        return True
    if page_no > int(cleanup.front_matter_scan_pages):
        return False
    lower_t = t.lower()
    hit = sum(1 for m in _FRONT_MATTER_MARKERS if m.lower() in lower_t)
    strong = any(k in t for k in ("序言", "前言", "再版说明", "出版说明"))
    return (strong or hit >= int(cleanup.front_matter_min_marker_hits)) and len(t) < 3500


def _looks_like_toc_page(text: str, cfg: AppConfig) -> bool:
    t = _normalize_text(text)
    if not t:
        return False
    lower_t = t.lower()
    dotted = t.count("........") + t.count("......") + t.count("...")
    has_marker = any(m in lower_t for m in [x.lower() for x in _TOC_MARKERS]) or "目录" in t or "目 录" in t
    return (has_marker and len(t) < 12000) or dotted >= int(cfg.pdf_cleanup.toc_page_min_dotted)


def _looks_like_noise_para(para: str) -> bool:
    p = (para or "").strip()
    return (not p) or len(p) <= 2


def _looks_like_toc_para(para: str, cfg: AppConfig) -> bool:
    p = (para or "").strip()
    if not p:
        return False
    dotted = p.count("........") + p.count("......") + p.count("...")
    lower_p = p.lower()
    has_marker = any(m in lower_p for m in [x.lower() for x in _TOC_MARKERS]) or "目录" in p or "目 录" in p
    return (has_marker and len(p) < 220) or dotted >= int(cfg.pdf_cleanup.toc_para_min_dotted)


def _looks_ocr_garbled(para: str, cfg: AppConfig) -> bool:
    p = (para or "").strip()
    if not p or len(p) < 8:
        return False
    bad = sum(1 for ch in p if ch in "�□◻◼■")
    ratio = bad / max(1, len(p))
    return bad >= int(cfg.pdf_cleanup.garbled_min_bad_chars) and ratio >= float(cfg.pdf_cleanup.garbled_ratio)


def _split_table_cells(line: str) -> list[str]:
    raw = re.split(r"\s{2,}|\t+|\s*\|\s*", line.strip())
    cells = [x.strip(" |") for x in raw if x and x.strip(" |")]
    if len(cells) <= 1:
        return []
    return cells


def _looks_like_table_line(line: str, min_cols: int) -> bool:
    cells = _split_table_cells(line)
    if len(cells) >= min_cols:
        return True
    num_tokens = re.findall(r"\d+(?:\.\d+)?", line)
    cjk_words = re.findall(r"[\u4e00-\u9fffA-Za-z_]+", line)
    return len(num_tokens) >= max(2, min_cols) and len(cjk_words) >= 1 and "  " in line


def _maybe_parse_table_para(para: str, page_no: int, order: int, cfg: AppConfig) -> Block | None:
    if not bool(cfg.pdf_cleanup.enable_block_type_detection):
        return None
    lines = [ln.strip() for ln in _normalize_text(para).split("\n") if ln.strip()]
    if not lines:
        return None

    caption = ""
    if _TABLE_CAPTION_RE.match(lines[0]):
        caption = lines[0]
        body_lines = lines[1:]
    else:
        body_lines = lines

    table_like = [ln for ln in body_lines if _looks_like_table_line(ln, int(cfg.pdf_cleanup.table_min_cols))]
    if not caption and len(table_like) < int(cfg.pdf_cleanup.table_min_lines):
        return None
    if caption and len(body_lines) < 1:
        return None

    rows: list[list[str]] = []
    for ln in body_lines:
        cells = _split_table_cells(ln)
        if cells:
            rows.append(cells)

    if not rows:
        return None

    headers: list[str] = []
    body_rows = rows
    if rows:
        first = rows[0]
        non_numeric = sum(1 for c in first if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", c))
        if non_numeric >= max(1, len(first) // 2):
            headers = first
            body_rows = rows[1:] if len(rows) > 1 else []
    if not body_rows and headers:
        return None

    return Block(
        page=page_no,
        type="table",
        order=order,
        text=_normalize_text(para),
        meta={
            "caption": caption,
            "headers": headers,
            "rows": body_rows or rows,
            "table_id": f"p{page_no}_o{order}",
        },
    )


def _maybe_parse_figure_para(para: str, page_no: int, order: int, cfg: AppConfig) -> Block | None:
    if not bool(cfg.pdf_cleanup.enable_block_type_detection):
        return None
    lines = [ln.strip() for ln in _normalize_text(para).split("\n") if ln.strip()]
    if not lines:
        return None
    if not _FIGURE_CAPTION_RE.match(lines[0]):
        return None
    caption = lines[0]
    body = "\n".join(lines[1:]).strip()
    return Block(
        page=page_no,
        type="figure",
        order=order,
        text=body,
        meta={"caption": caption},
    )


def pages_to_blocks(pages, cfg: AppConfig) -> list[Block]:
    blocks: list[Block] = []
    order = 0
    kept_paras = 0
    dropped_noise = 0
    dropped_toc = 0
    dropped_garbled = 0
    type_counts = {"text": 0, "table": 0, "figure": 0}

    for p in pages:
        page_no = int(getattr(p, "page", 0))
        page_text = getattr(p, "text", "") or ""
        paras = _split_paragraphs(page_text)

        for para in paras:
            if _looks_like_noise_para(para):
                dropped_noise += 1
                continue

            if _looks_like_toc_para(para, cfg):
                dropped_toc += 1
                if cfg.pdf_cleanup.drop_flagged_toc_para:
                    continue

            if _looks_ocr_garbled(para, cfg):
                dropped_garbled += 1
                if cfg.pdf_cleanup.drop_flagged_garbled_para:
                    continue

            block = (
                _maybe_parse_table_para(para, page_no, order, cfg)
                or _maybe_parse_figure_para(para, page_no, order, cfg)
                or Block(page=page_no, type="text", order=order, text=para, meta={})
            )

            blocks.append(block)
            type_counts[block.type] = type_counts.get(block.type, 0) + 1
            order += 1
            kept_paras += 1

    print(f"[debug] kept_paras={kept_paras}")
    print(f"[debug] dropped_noise={dropped_noise}")
    print(f"[debug] dropped_toc={dropped_toc}")
    print(f"[debug] dropped_garbled={dropped_garbled}")
    print(f"[debug] block_types={type_counts}")
    return blocks


def ingest_pdf(pdf_path: Path, cfg: AppConfig, *, force_ocr: bool = False, overwrite: bool = False) -> int:
    pdf_path = Path(pdf_path)
    db = DB.create(cfg)

    title = pdf_path.name
    sha = sha256_file(pdf_path)
    doc_id = get_or_create_document_compat(
        db,
        source=str(pdf_path),
        title=title,
        sha256=sha,
        mime=PDF_MIME,
        local_path=str(pdf_path),
        meta_json={"ingest_service": "ingest_pdf_rich"},
    )

    existing_chunks = count_chunks_for_doc_compat(db, doc_id)
    if existing_chunks > 0 and not overwrite:
        print("[info] chunks already exist; skipping OCR/ingest (use --overwrite to replace)")
        return doc_id
    if overwrite and existing_chunks > 0:
        delete_chunks_for_doc_compat(db, doc_id)

    pages = ocr_pdf_pages(pdf_path, cfg, force_ocr=force_ocr)
    if force_ocr:
        force_total = sum(len(getattr(p, "text", "") or "") for p in pages)
        print(f"[debug] force_ocr_pages={len(pages)}")
        print(f"[debug] force_ocr_total_chars={force_total}")
        if force_total <= 0:
            raise RuntimeError("force_ocr=True but OCR produced no text")

    print(f"[debug] raw_pages={len(pages)}")
    print(f"[debug] raw_total_chars={sum(len(getattr(p, 'text', '') or '') for p in pages)}")
    print(f"[debug] after_drop_first_pages={len(pages)}")

    before = len(pages)
    filtered_pages = []
    for p in pages:
        page_no = int(getattr(p, "page", 0))
        if _looks_like_front_matter_page(getattr(p, "text", "") or "", page_no, cfg):
            continue
        filtered_pages.append(p)
    pages = filtered_pages
    print(f"[debug] after_drop_front_matter={len(pages)} (dropped={before - len(pages)})")

    before = len(pages)
    pages = [p for p in pages if not _looks_like_toc_page(getattr(p, "text", "") or "", cfg)]
    print(f"[debug] after_drop_toc_pages={len(pages)} (dropped={before - len(pages)})")
    print(f"[debug] after_page_filters_total_chars={sum(len(getattr(p, 'text', '') or '') for p in pages)}")

    blocks = pages_to_blocks(pages, cfg)
    print(f"[debug] blocks={len(blocks)}")

    rows = chunk_blocks_to_rows(blocks, ctx=build_chunk_context(cfg))
    print(f"[debug] rows={len(rows)}")
    if rows:
        sample = rows[0]
        print(f"[debug] sample_row_type={sample.chunk_type} page=({sample.page_start},{sample.page_end}) char_len={sample.char_len}")

    insert_chunks_compat(db, doc_id=doc_id, rows=rows)
    section_count = sync_document_sections_for_doc(db, doc_id=doc_id)
    if section_count:
        print(f"[step] sync document_sections -> {section_count}")

    print("[step] fetch active chunks -> pending rebuild")
    rebuild_all(cfg, db, batch=cfg.rebuild.batch_size, wipe_db=True, wipe_faiss=True)
    return doc_id
