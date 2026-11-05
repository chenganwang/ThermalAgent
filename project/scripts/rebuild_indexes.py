from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse

from services.retrieval_service.config import load_config
from services.retrieval_service.db import DB
from services.ingest_service.rebuild_embeddings import rebuild_all

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    db = DB.create(cfg)
    rebuild_all(cfg, db, batch=args.batch, wipe_db=True, wipe_faiss=True, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
