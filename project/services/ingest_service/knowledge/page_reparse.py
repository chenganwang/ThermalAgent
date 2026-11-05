from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from services.ingest_service.chunking import build_chunk_context, chunk_blocks_to_rows
from services.ingest_service.external_sources import sha256_file
from services.ingest_service.ingest_pdf_rich import pages_to_blocks
from services.ingest_service.ocr_pdf import extract_pdf_text_pages
from services.retrieval_service.config import AppConfig

from .corrections import KnowledgeCorrectionError


STANDARD_PDF_TEXT_STRATEGY = "standard_pdf_text"


class CanonicalPageParser:
    """Select one PDF text-layer page and reuse the canonical block/chunk path."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def parse(self, path: Path, *, page_number: int, strategy: str) -> dict[str, Any]:
        source = Path(path)
        if strategy != STANDARD_PDF_TEXT_STRATEGY or source.suffix.lower() != ".pdf":
            raise KnowledgeCorrectionError(
                "PAGE_REPARSE_STRATEGY_UNSUPPORTED",
                "Only the standard PDF text parser is available.",
                status_code=422,
            )
        page = int(page_number)
        if page <= 0:
            raise KnowledgeCorrectionError("PAGE_ID_INVALID", "Invalid page identifier.", status_code=422)
        pages = extract_pdf_text_pages(source)
        selected = next((item for item in pages if int(item.page) == page), None)
        if selected is None:
            raise KnowledgeCorrectionError("PAGE_NOT_FOUND", "The requested page does not exist.", status_code=404)
        blocks = pages_to_blocks([selected], self.cfg)
        context = replace(build_chunk_context(self.cfg), semantic_split_enable=False, use_token_budget=False)
        rows = chunk_blocks_to_rows(blocks, ctx=context)
        digest = sha256_file(source)
        public_rows: list[dict[str, Any]] = []
        for row in rows:
            raw = asdict(row) if is_dataclass(row) else dict(row)
            text = str(raw.get("text") or "")
            metadata = dict(raw.get("meta_json")) if isinstance(raw.get("meta_json"), dict) else {}
            metadata.update({
                "source_file": source.name,
                "source_sha256": digest,
                "parser_strategy": STANDARD_PDF_TEXT_STRATEGY,
                "reparsed_page": page,
            })
            public_rows.append({
                "chunk_index": int(raw.get("chunk_index") or 0),
                "page_start": page,
                "page_end": page,
                "chunk_type": str(raw.get("chunk_type") or "text"),
                "section_path": raw.get("section_path"),
                "text": text,
                "char_len": len(text),
                "token_len": raw.get("token_len"),
                "content_hash": sha256(text.encode("utf-8")).hexdigest(),
                "quality_score": raw.get("quality_score"),
                "meta_json": metadata,
                "is_active": 1,
            })
        return {
            "parser": "pdf_text_layer",
            "parser_version": None,
            "strategy": STANDARD_PDF_TEXT_STRATEGY,
            "page_number": page,
            "page_count": len(pages),
            "character_count": len(str(selected.text or "")),
            "rows": public_rows,
            "warnings": [],
        }


__all__ = ["CanonicalPageParser", "STANDARD_PDF_TEXT_STRATEGY"]
