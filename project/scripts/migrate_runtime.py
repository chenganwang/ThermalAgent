from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
from pathlib import Path

from services.retrieval_service.config import load_config

def main() -> None:
    cfg = load_config()
    report = {
        "project_root": str(cfg.paths.project_root),
        "data_dir": str(cfg.paths.data_dir),
        "faiss_dir": str(cfg.paths.faiss_dir),
        "bm25_dir": str(cfg.paths.bm25_dir),
        "mysql": {
            "host": cfg.mysql.host,
            "port": cfg.mysql.port,
            "user": cfg.mysql.user,
            "database": cfg.mysql.database,
        },
        "notes": [
            "Copy runtime data directories before switching hosts.",
            "Run scripts/init_db.py on the target host before ingest or rebuild.",
            "Run scripts/validate_runtime.py after migration.",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
