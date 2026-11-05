from __future__ import annotations
from .config import load_config
from .db import DB

def show_latest(n: int = 20):
    cfg = load_config()
    db = DB.create(cfg)
    rows = db.fetchall("SELECT id, query_text, topk, latency_ms, created_at FROM retrieval_log ORDER BY id DESC LIMIT %s", (n,))
    for r in rows:
        print(r)

if __name__ == "__main__":
    show_latest()
