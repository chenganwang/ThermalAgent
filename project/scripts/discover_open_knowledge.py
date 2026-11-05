"""Search public Crossref metadata by topic; never download or approve fulltext."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.ingest_service.web_discovery import discover_topics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", action="append", required=True, help="Public technical search topic, not project secrets; repeat up to five distinct topics")
    parser.add_argument("--rows", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/open_knowledge_discovery")
    parser.add_argument("--refresh", action="store_true", help="Repeat successful topic query; preserve prior response/attempt snapshots")
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    result = discover_topics(ROOT, args.topic, output_dir=output, rows=args.rows, refresh=args.refresh)
    selected = {" ".join(topic.split()).casefold() for topic in args.topic}
    failed = [row for row in result["topics"] if row["topic"].casefold() in selected and row["status"] == "failed"]
    print(json.dumps({"manifest": str(output / "discovery_manifest.json"), "distinct_metadata_candidates": len(result["candidates"]), "failed_selected_topics": len(failed), "fulltext_requests": 0, "human_reviewed_count": 0, "license_approved_count": 0, "production_writes": 0}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
