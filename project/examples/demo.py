"""Search the original example notes with the project's BM25 implementation."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.retrieval_service.bm25_index import BM25IndexManager
from services.retrieval_service.bm25_tokenizer import bm25_tokenize
from services.retrieval_service.config import load_config

NOTES = Path(__file__).with_name("cooling-notes.md")


def sections():
    rows = []
    for block in NOTES.read_text(encoding="utf-8").split("\n## ")[1:]:
        title, body = block.split("\n", 1)
        rows.append((title.strip(), body.strip()))
    return rows


def search(query):
    rows = sections()
    texts = [title + "\n" + body for title, body in rows]
    with TemporaryDirectory() as tmp:
        folder = Path(tmp)
        cfg = load_config(folder)
        paths = replace(cfg.paths, bm25_dir=folder, bm25_corpus_path=folder / "notes.pkl",
                        bm25_meta_path=folder / "notes.meta.json")
        manager = BM25IndexManager(replace(cfg, paths=paths))
        manager.save(chunk_ids=list(range(1, len(rows) + 1)), tokenized_corpus=[bm25_tokenize(t) for t in texts],
                     corpus_texts=texts)
        hits = manager.search(query, topn=3)
    return [{"chunk_id": i, "source": NOTES.name, "section": rows[i-1][0],
             "score": round(score, 4), "text": rows[i-1][1]} for i, score in hits]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="并联支路如何分配流量？")
    parser.add_argument("--export-docx", type=Path, help="Write the same notes for the production ingestion CLI.")
    args = parser.parse_args()
    if args.export_docx:
        from docx import Document
        document = Document()
        document.core_properties.author = "ThermalAgent"
        for title, body in sections():
            document.add_heading(title, level=1)
            document.add_paragraph(body)
        args.export_docx.parent.mkdir(parents=True, exist_ok=True)
        with args.export_docx.open("xb") as output:
            document.save(output)
        print(args.export_docx)
    else:
        print(json.dumps(search(args.query), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
