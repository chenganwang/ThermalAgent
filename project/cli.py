from __future__ import annotations

from services.retrieval_service.cli import main as retrieval_main


def main():
    """Keep existing commands; expose the isolated knowledge pipeline explicitly."""
    import sys
    import importlib
    commands = {'collect': 'collect_open_knowledge', 'parse': 'parse_knowledge_documents',
                'prepare': 'prepare_open_knowledge', 'stage': 'manage_knowledge_staging',
                'evaluate': 'evaluate_vnext_retrieval', 'restore':'restore_knowledge_snapshot',
                'discover':'discover_open_knowledge'}
    if len(sys.argv) < 2 or sys.argv[1] != 'knowledge':
        return retrieval_main()
    if len(sys.argv) < 3 or sys.argv[2] in {'-h','--help'}:
        print('Knowledge workflow: cli.py knowledge {discover,collect,parse,prepare,stage,restore,evaluate} --help')
        return
    if sys.argv[2] not in commands:
        raise SystemExit('Unknown knowledge command. Use: cli.py knowledge --help')
    module = importlib.import_module('scripts.' + commands[sys.argv[2]])
    original = sys.argv
    sys.argv = [original[0] + ' knowledge ' + original[2], *original[3:]]
    try:
        status = module.main()
    finally:
        sys.argv = original
    if isinstance(status, int) and status:
        raise SystemExit(status)


if __name__ == "__main__":
    main()
