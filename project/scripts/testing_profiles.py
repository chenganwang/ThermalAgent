"""Additive test layers; legacy suite selection remains available unchanged."""
from pathlib import Path

PROFILES = ('offline', 'module', 'agent', 'tools', 'rag', 'regression', 'benchmark', 'frontend', 'external')


def layers_for(record):
    name = Path(str(record.get('path') or '')).stem.removeprefix('test_')
    layers = []
    if record.get('category') in {'unit', 'contract', 'matlab_mock'}:
        layers.append('module')
    if any(word in name for word in ('agent', 'task', 'closed_loop', 'engineering_run', 'engineering_reference')):
        layers.append('agent')
    if any(word in name for word in ('tool', 'calculat', 'solver', 'physics', 'hydraulic', 'thermal_network', 'engineering_closed_loop', 'benchmark')):
        layers.append('tools')
    if any(word in name for word in ('retriev', 'knowledge', 'index', 'chunk', 'source', 'demoqa', 'ku_', 'bm25', 'faiss', 'ingest')):
        layers.append('rag')
    if record.get('category') in {'contract', 'regression', 'integration', 'evaluation'} or 'closed_loop' in name or 'benchmark' in name:
        layers.append('regression')
    if 'benchmark' in name:
        layers.append('benchmark')
    if record.get('requires_frontend'):
        layers.append('frontend')
    return layers


def select_profile(manifest, profile, *, include_real_resources=False):
    if profile not in PROFILES:
        raise ValueError(f'unknown test profile: {profile}')
    if profile == 'external' and not include_real_resources:
        raise PermissionError('external profile requires --include-real-resources')
    selected, excluded = [], []
    for record in manifest['tests']:
        local = not record.get('requires_real_resource')
        in_layer = profile in {'offline', 'external'} or profile in layers_for(record)
        reason = None
        if not record.get('enabled', True):
            reason = 'disabled in manifest'
        elif not in_layer:
            reason = 'outside requested layer'
        elif profile != 'external' and not local:
            reason = 'external/resource test requires explicit opt-in'
        elif profile == 'external' and local:
            reason = 'covered by offline profile'
        if reason:
            excluded.append({'path': record['path'], 'reason': reason})
        else:
            selected.append({**record, 'id': Path(record['path']).stem.removeprefix('test_'), 'command': f"python {record['path']}"})
    return selected, excluded
