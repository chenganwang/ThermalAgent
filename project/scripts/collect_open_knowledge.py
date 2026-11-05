"""Acquire approved public sources; default command only previews metadata."""
from pathlib import Path
import argparse
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from services.ingest_service.web_sources import SourceCollector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True, help="Reviewed source metadata JSON containing sources[]")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/open_knowledge")
    parser.add_argument("--collect", action="store_true", help="Perform bounded HTTPS requests into local draft manifest")
    parser.add_argument("--refresh", action="store_true", help="Fetch new immutable versions; never overwrite old content")
    parser.add_argument("--source-id", action="append", default=[], help="Limit to these source IDs")
    parser.add_argument("--max-bytes", type=int, default=32 * 1024 * 1024)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8-sig"))
    sources = catalog["sources"]
    if args.source_id:
        sources = [source for source in sources if source["source_id"] in args.source_id]
        if {source["source_id"] for source in sources} != set(args.source_id):
            parser.error("Unknown requested source ID")
    if not args.collect:
        print(json.dumps({"mode": "preview_no_network", "sources": [{"source_id": source["source_id"], "url": source["url"], "title": source["title"], "fulltext_permitted": source.get("license", {}).get("allow_fulltext") is True} for source in sources]}, ensure_ascii=False, indent=2))
        return 0
    output = args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir
    manifest = SourceCollector(PROJECT_ROOT, output_dir=output, max_bytes=args.max_bytes).collect(sources, refresh=args.refresh)
    counts = {status: sum(item["status"] == status for item in manifest["sources"]) for status in ("downloaded", "metadata_only", "failed")}
    selected_ids = {source["source_id"] for source in sources}
    selected_counts = {status: sum(item["source_id"] in selected_ids and item["status"] == status for item in manifest["sources"]) for status in counts}
    print(json.dumps({"manifest": str(output / "manifest.json"), "counts": counts, "selected_counts": selected_counts, "human_reviewed": manifest["human_reviewed_count"], "production_writes": 0}, ensure_ascii=False))
    return 1 if selected_counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
