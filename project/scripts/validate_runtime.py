from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
from pathlib import Path

from services.retrieval_service.config import load_config
from services.retrieval_service.db import DB
from services.retrieval_service.embed_index import validate_index_vs_db
from services.retrieval_service.bm25_index import validate_bm25_vs_db

def main() -> None:
    cfg = load_config()
    db = DB.create(cfg)
    report = {
        "paths": {
            "project_root": str(cfg.paths.project_root),
            "data_dir": str(cfg.paths.data_dir),
            "faiss_dir_exists": cfg.paths.faiss_dir.exists(),
            "bm25_dir_exists": cfg.paths.bm25_dir.exists(),
        },
        "faiss": validate_index_vs_db(cfg, db),
        "bm25": validate_bm25_vs_db(cfg, db),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main()
