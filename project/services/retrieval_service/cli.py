from __future__ import annotations
import argparse
import json
import sys

from .agent_orchestrator import ThermalAgent
from .config import load_config
from .db import DB
from .embed_index import validate_index_vs_db
from .bm25_index import validate_bm25_vs_db
from .rag_chain import query as rag_query
from .indexing.active_bundle import resolve_active_bundle
from .indexing.diagnostics.read_only_store import SelectOnlyChunkStore

def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> None:
    _configure_console_encoding()
    parser = argparse.ArgumentParser(description="Retrieval service CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_query = sub.add_parser("query")
    p_query.add_argument("question")
    p_query.add_argument("--topk", type=int, default=None)
    p_query.add_argument("--neighbor-window", type=int, default=None)

    p_validate = sub.add_parser("validate-index")

    p_agent = sub.add_parser("agent-answer")
    p_agent.add_argument("question")
    p_agent.add_argument("--session-id", default="cli")
    p_agent.add_argument("--topk", type=int, default=None)
    p_agent.add_argument("--text", action="store_true", help="Print only the answer text.")

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "query":
        try:
            print(rag_query(cfg, args.question, topk=args.topk, neighbor_window=args.neighbor_window))
        except Exception as exc:
            print(f"[error] retrieval failed: {exc}", file=sys.stderr)
            raise SystemExit(2)
        return

    if args.cmd == "agent-answer":
        result = ThermalAgent(cfg=cfg).answer(args.question, session_id=args.session_id, top_k=args.topk)
        if args.text:
            print(result["answer"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    try:
        bundle = resolve_active_bundle(cfg)
        db = SelectOnlyChunkStore(cfg)
    except Exception as exc:
        print(f"[error] database connection failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
    try:
        faiss_result = validate_index_vs_db(cfg, db, bundle=bundle)
        bm25_result = validate_bm25_vs_db(cfg, db, bundle=bundle)
        print("[FAISS]")
        for k, v in faiss_result.items():
            print(f"{k}: {v}")
        print("\n[BM25]")
        for k, v in bm25_result.items():
            print(f"{k}: {v}")
    finally:
        db.close()
    if not (faiss_result["is_consistent"] and bm25_result["is_consistent"]):
        raise SystemExit(3)

if __name__ == "__main__":
    main()
