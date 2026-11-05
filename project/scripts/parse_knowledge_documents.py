"""Parse local source manifests and compare chunk policies without writing a DB.

No network, embedding model loading or implicit OCR. Output is resumable by
source hash + parser/options; a lock rejects overlapping writers.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.ingest_service.structured_document import PARSER_VERSION, parse_document, sha256_file
from services.ingest_service.structured_chunking import CHUNK_VERSION, STRATEGIES, chunk_document


def _write(path: Path, value, *, lines=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    text = ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in value) if lines else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


@contextmanager
def memory_sample():
    stats = {'rss_start_bytes': None, 'rss_peak_sampled_bytes': None, 'rss_sampling_interval_seconds': .025,
             'scope': 'process RSS sampled at 25ms; not GPU or isolated per-function allocation'}
    stop = threading.Event()
    try:
        import psutil
        process = psutil.Process()
        get_rss = lambda: process.memory_info().rss
    except ImportError:
        get_rss = None
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in
                    ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
                     'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            def get_rss():
                counters = Counters()
                counters.cb = ctypes.sizeof(counters)
                if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                    raise OSError('GetProcessMemoryInfo failed')
                return counters.WorkingSetSize
    if get_rss:
        stats['rss_start_bytes'] = stats['rss_peak_sampled_bytes'] = get_rss()
        def sample():
            while not stop.wait(.025):
                stats['rss_peak_sampled_bytes'] = max(stats['rss_peak_sampled_bytes'], get_rss())
        thread = threading.Thread(target=sample, daemon=True)
        thread.start()
    else:
        stats['scope'] = 'unavailable: no process RSS reader'
        thread = None
    try:
        yield stats
    finally:
        stop.set()
        if thread:
            thread.join(timeout=1)


def run(manifest: dict, output: Path, *, strategies=STRATEGIES, options=None, embeddings=None, resume=False):
    output = output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('output must stay inside the project')
    options = dict(options or {})
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.parser.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    started = time.perf_counter()
    try:
        policy = {'parser': PARSER_VERSION, 'chunker': CHUNK_VERSION, 'strategies': list(strategies), 'options': options}
        policy_path = output / 'policy.json'
        if policy_path.exists() and json.loads(policy_path.read_text(encoding='utf-8')) != policy:
            raise ValueError('existing output policy differs; use a new output directory')
        if policy_path.exists() and not resume:
            raise ValueError('output exists; explicitly use --resume or a new output directory')
        _write(policy_path, policy)
        records = []
        aggregated = {s: [] for s in strategies}
        aggregated_parents = {s: [] for s in strategies}
        with memory_sample() as memory:
            for row in manifest.get('sources', []):
                source_id = str(row.get('source_id') or '')
                local = row.get('local_path') or row.get('file_path')
                if not source_id or not local:
                    records.append({'source_id': source_id, 'status': 'metadata_only', 'reason': 'no local source'})
                    continue
                path = Path(local)
                path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
                if not path.is_relative_to(ROOT.parent):
                    raise ValueError('source file must remain inside project package')
                try:
                    digest = sha256_file(path)
                    if row.get('sha256') and row['sha256'] != digest:
                        raise ValueError('source manifest hash mismatch')
                    key = hashlib.sha256((source_id + digest + json.dumps(policy, sort_keys=True) + json.dumps(row, sort_keys=True)).encode()).hexdigest()[:24]
                    folder = output / 'documents' / key
                    parsed_path = folder / 'parsed.json'
                    if resume and parsed_path.exists():
                        checksum_path = folder / 'parsed.sha256'
                        if not checksum_path.exists() or checksum_path.read_text(encoding='ascii').strip() != sha256_file(parsed_path):
                            raise ValueError('parsed checkpoint checksum mismatch; preserve artifact and use a new output directory')
                        parsed = json.loads(parsed_path.read_text(encoding='utf-8'))
                        if parsed['document']['sha256'] != digest or parsed['parser']['version'] != PARSER_VERSION:
                            raise ValueError('checkpoint identity mismatch')
                    else:
                        parsed = parse_document(path, source_id, row, options)
                        _write(parsed_path, parsed)
                        (folder / 'parsed.sha256').write_text(sha256_file(parsed_path) + '\n', encoding='ascii')
                    item = {'source_id': source_id, 'sha256': digest, 'status': 'parsed',
                            'parsed_path': str(parsed_path.relative_to(ROOT)), 'metrics': parsed['metrics'], 'strategies': {}}
                    for strategy in strategies:
                        supplied = (embeddings or {}).get(source_id)
                        result = chunk_document(parsed, strategy, options, block_embeddings=supplied if strategy == 'semantic' else None)
                        _write(folder / f'{strategy}.json', result)
                        item['strategies'][strategy] = {'status': result['status'], 'metrics': result['metrics'], 'reason': result.get('reason')}
                        aggregated[strategy].extend(result['chunks'])
                        aggregated_parents[strategy].extend(result['parents'])
                    records.append(item)
                except Exception as exc:
                    records.append({'source_id': source_id, 'status': 'failed', 'error': type(exc).__name__ + ': ' + str(exc)})
                _write(output / 'checkpoint.json', {'policy': policy, 'records': records, 'completed': False})
        for strategy in strategies:
            _write(output / strategy / 'chunks.jsonl', aggregated[strategy], lines=True)
            _write(output / strategy / 'parents.jsonl', aggregated_parents[strategy], lines=True)
        summary = {'schema_version': 'parser-experiment-v1', 'policy': policy, 'records': records,
                   'counts': dict(__import__('collections').Counter(r['status'] for r in records)),
                   'elapsed_seconds': time.perf_counter() - started, 'memory': memory,
                   'network_calls': 0, 'database_writes': 0, 'embedding_model_loads': 0,
                   'human_reviewed_increment': 0, 'completed': True}
        _write(output / 'results.json', summary)
        _write(output / 'checkpoint.json', summary)
        return summary
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--strategies', nargs='+', choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument('--max-chars', type=int, default=1000)
    parser.add_argument('--parent-max-chars', type=int, default=3000)
    parser.add_argument('--pages', help='One-based comma-separated page selection; omit for all pages')
    parser.add_argument('--embeddings-json', type=Path, help='source_id -> block_id -> vector; JSON, never pickle')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    options = {'max_chars': args.max_chars, 'parent_max_chars': args.parent_max_chars}
    if args.pages:
        options['pages'] = [int(p) for p in args.pages.split(',')]
    result = run(json.loads(args.manifest.read_text(encoding='utf-8')), args.output_dir,
                 strategies=args.strategies, options=options,
                 embeddings=json.loads(args.embeddings_json.read_text(encoding='utf-8')) if args.embeddings_json else None,
                 resume=args.resume)
    print(json.dumps({k: result[k] for k in ('counts', 'elapsed_seconds', 'memory')}, ensure_ascii=False))
    return 1 if result['counts'].get('failed', 0) else 0


if __name__ == '__main__':
    raise SystemExit(main())
