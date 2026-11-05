"""Replay an audited knowledge snapshot into a new isolated SQLite file."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.ingest_service.knowledge.staging_store import StagingStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--sqlite',required=True,type=Path)
    args=parser.parse_args()
    if not args.sqlite.resolve().is_relative_to(ROOT.parent.resolve()):
        parser.error('restore target must remain inside project package')
    snapshot=json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    store=StagingStore.restore_sqlite_snapshot(args.sqlite,snapshot)
    try:
        print(json.dumps({'status':'restored_to_new_isolated_sqlite','matches_snapshot':store.snapshot()==snapshot,
            'tables':{k:v['count'] for k,v in snapshot.items()},'production_written':False},ensure_ascii=False))
    finally:store.close()


if __name__=='__main__':main()
