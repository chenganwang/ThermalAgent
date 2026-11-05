from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import hashlib
import logging

from services.retrieval_service.config import AppConfig
from .chunking.page_text import PageText
from .ocr_cache import versioned_cache_dir, write_cached_page

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _ensure_cache_dir(cfg: AppConfig, pdf_sha: str) -> Path:
    import pytesseract  # type: ignore

    command = cfg.ocr.tesseract_cmd or pytesseract.pytesseract.tesseract_cmd
    return versioned_cache_dir(cfg, pdf_sha, effective_tesseract_cmd=command)


def _cache_path(cache_dir: Path, page: int) -> Path:
    return cache_dir / f"page_{page:04d}.txt"


def _normalize_page_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _looks_text_layer_usable(text: str, min_chars: int) -> bool:
    t = _normalize_page_text(text)
    if len(t) < int(min_chars):
        return False
    bad = sum(1 for ch in t if ch in "�□◻◼■")
    return bad < max(6, len(t) // 4)


def _extract_pdf_text_pages_pymupdf(pdf_path: Path, *, max_pages: Optional[int] = None) -> List[PageText]:
    import fitz  # type: ignore

    doc = fitz.open(str(pdf_path))
    pages: List[PageText] = []
    try:
        total = len(doc)
        limit = min(total, max_pages) if max_pages is not None else total
        for idx in range(limit):
            page = doc.load_page(idx)
            pages.append(PageText(page=idx + 1, text=_normalize_page_text(page.get_text("text") or "")))
    finally:
        doc.close()
    return pages


def _extract_pdf_text_pages_pypdf(pdf_path: Path, *, max_pages: Optional[int] = None) -> List[PageText]:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    limit = min(total, max_pages) if max_pages is not None else total
    pages: List[PageText] = []
    for idx in range(limit):
        text = reader.pages[idx].extract_text() or ""
        pages.append(PageText(page=idx + 1, text=_normalize_page_text(text)))
    return pages


def extract_pdf_text_pages(pdf_path: Path, *, max_pages: Optional[int] = None) -> List[PageText]:
    last_error: Exception | None = None
    for extractor in (_extract_pdf_text_pages_pymupdf, _extract_pdf_text_pages_pypdf):
        try:
            pages = extractor(pdf_path, max_pages=max_pages)
            if pages:
                return pages
        except Exception as e:
            last_error = e
            continue
    if last_error is not None:
        logger.info("text-layer extraction unavailable for %s: %s", pdf_path, last_error)
    return []


def _ocr_single_page(pdf_path: Path, cfg: AppConfig, *, page: int, cache_dir: Path, force_refresh: bool = False) -> str:
    cache_file = _cache_path(cache_dir, page)
    if cache_file.exists() and not force_refresh:
        return cache_file.read_text(encoding="utf-8", errors="ignore")

    from pdf2image import convert_from_path  # type: ignore
    import pytesseract  # type: ignore

    if cfg.ocr.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = cfg.ocr.tesseract_cmd

    images = convert_from_path(
        str(pdf_path),
        first_page=page,
        last_page=page,
        dpi=int(getattr(cfg.ocr, "render_dpi", 300) or 300),
    )
    if not images:
        return ""
    txt = pytesseract.image_to_string(images[0], lang=cfg.ocr.lang or "chi_sim+eng")
    txt = _normalize_page_text(txt)
    write_cached_page(cache_file, txt)
    return txt


def _ocr_pdf_all_pages(pdf_path: Path, cfg: AppConfig, *, max_pages: Optional[int] = None, force_refresh: bool = False) -> List[PageText]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    pdf_sha = _sha256_file(pdf_path)
    cache_dir = _ensure_cache_dir(cfg, pdf_sha)
    pages: List[PageText] = []
    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            break
        try:
            txt = _ocr_single_page(pdf_path, cfg, page=page, cache_dir=cache_dir, force_refresh=force_refresh)
        except Exception as e:
            if not pages:
                raise RuntimeError(
                    "OCR failed. On Windows you likely need Poppler for pdf2image and Tesseract for OCR."
                ) from e
            break
        if txt == "" and not _cache_path(cache_dir, page).exists():
            break
        pages.append(PageText(page=page, text=txt))
        page += 1
    return pages


def ocr_pdf_pages(pdf_path: Path, cfg: AppConfig, *, max_pages: Optional[int] = None, force_ocr: bool = False) -> List[PageText]:
    """Extract a PDF into per-page text.

    Strategy:
    1. If force_ocr=True, freshly OCR every page, ignoring text layers and
       cached results. Changed cached text is archived before replacement.
    2. Otherwise prefer text-layer extraction.
    3. For weak/empty text-layer pages, OCR only those pages.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    if force_ocr or not bool(getattr(cfg.ocr, "prefer_text_layer", True)):
        return _ocr_pdf_all_pages(pdf_path, cfg, max_pages=max_pages, force_refresh=force_ocr)

    text_pages = extract_pdf_text_pages(pdf_path, max_pages=max_pages)
    if not text_pages:
        return _ocr_pdf_all_pages(pdf_path, cfg, max_pages=max_pages)

    pdf_sha = _sha256_file(pdf_path)
    cache_dir: Path | None = None
    min_chars = int(getattr(cfg.ocr, "text_layer_min_chars", 80) or 80)
    out: List[PageText] = []
    for page_item in text_pages:
        text = _normalize_page_text(page_item.text)
        if _looks_text_layer_usable(text, min_chars=min_chars):
            out.append(PageText(page=page_item.page, text=text))
            continue
        try:
            if cache_dir is None:
                cache_dir = _ensure_cache_dir(cfg, pdf_sha)
            ocr_text = _ocr_single_page(pdf_path, cfg, page=page_item.page, cache_dir=cache_dir)
            final_text = ocr_text if len(ocr_text) >= len(text) else text
        except Exception as e:
            logger.warning("OCR fallback failed for page %s of %s: %s", page_item.page, pdf_path, e)
            final_text = text
        out.append(PageText(page=page_item.page, text=_normalize_page_text(final_text)))
    return out


# Backward-compatible alias names

def ocr_pdf_to_pages(pdf_path: Path, cfg: AppConfig):
    return ocr_pdf_pages(pdf_path, cfg)


def ocr_pdf(pdf_path: Path, cfg: AppConfig):
    return ocr_pdf_pages(pdf_path, cfg)
