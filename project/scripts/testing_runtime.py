"""Local test workspace and environment, separate from application runtime."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import shutil
import socket

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'node_modules', '__pycache__', '.git', '.venv', '.pytest_cache', 'dist', 'build', 'runtime', 'runtime_data', 'reports'}
PREFIXES = ('MYSQL_', 'SIMULATION_', 'MATLAB_', 'FLUENT_', 'ADMIN_', 'RAG_', 'AGENT_', 'OLLAMA_', 'FEATURE_', 'GENERATED_MODEL_', 'CFD_', 'ENGINEERING_')


def copy_source_tree(source: Path, destination: Path) -> int:
    """Copy required source/resources, including .feature/.sql; no live secrets."""
    if not source.is_dir():
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for entry in source.iterdir():
        if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
            continue
        if entry.is_dir():
            if entry.name not in EXCLUDED:
                copied += copy_source_tree(entry, destination / entry.name)
        elif entry.name == '.env.example' or (not entry.name.startswith('.env') and entry.name != '.webui_secret_key' and entry.suffix.lower() not in {'.zip', '.pyc', '.pyo'}):
            shutil.copy2(entry, destination / entry.name)
            copied += 1
    return copied


@contextmanager
def isolated_runtime(output: Path, *, source_project: Path = PROJECT_ROOT, external: bool = False):
    output = output.resolve()
    package = output / 'workspace'
    project = package / 'project'
    if project.exists():
        raise FileExistsError('Test workspace already exists; use a new --output-dir')
    project.mkdir(parents=True)
    count = 0
    for name in ('services', 'scripts', 'config', 'docs', 'simulation_models', 'matlab', 'benchmarks', 'deploy', 'frontends', 'ingest_service'):
        count += copy_source_tree(source_project / name, project / name)
    for entry in source_project.iterdir():
        if entry.is_file() and (entry.name in {'.env.example', '.dockerignore'} or (entry.suffix.lower() in {'.py', '.md', '.txt', '.json', '.ps1', '.bat'} and not entry.name.startswith('.env'))):
            shutil.copy2(entry, project / entry.name)
            count += 1
    # These are read-only inputs to existing regression tests, never linked to
    # production. The audit archive is an explicitly named historical fixture.
    resources = ['data/reference', 'data/evaluation', 'indexes', 'runtime/engineering_audit']
    for name in resources:
        count += copy_source_tree(source_project / name, project / name)
    for name in ('thermal-frontend', 'rag_agent_schema_package'):
        count += copy_source_tree(source_project.parent / name, package / name)
    for name in ('package.json', 'package-lock.json'):
        source = source_project.parent / name
        if source.is_file():
            shutil.copy2(source, package / name)
    if (project / '.env.example').is_file():
        shutil.copy2(project / '.env.example', project / '.env')

    env = dict(os.environ)
    if not external:
        for key in list(env):
            if key.startswith(PREFIXES):
                env.pop(key)
    temp = project / 'runtime/test_tmp'
    temp.mkdir(parents=True)
    env.update({key: '1' for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
    env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', TEMP=str(temp), TMP=str(temp),
               RAG_PROJECT_ROOT=str(project), ENGINEERING_STORE_PATH=str(project / 'runtime/engineering.sqlite3'))
    with socket.socket() as guard:
        guard.bind(('127.0.0.1', 0))  # Hold the port without listening for the whole suite.
        if not external:
            env.update(MYSQL_HOST='127.0.0.1', MYSQL_PORT=str(guard.getsockname()[1]), MYSQL_DB='thermalagent_isolated_suite',
                       MYSQL_USER='isolated_test', MYSQL_PASSWORD='', RAG_API_KEY='', AGENT_ENABLE_LLM='false',
                       HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CFD_MODE='mock', FLUENT_ENABLED='false',
                       FLUENT_EXECUTION_ENABLED='false', SIMULATION_MATLAB_ENABLED='false', SIMULATION_MATLAB_ALLOW_ENGINE_START='false',
                       MATLAB_ENGINE_REAL_EXECUTION_ENABLED='false', MATLAB_SIMULATION_ENABLED='false',
                       THERMAL_TEST_OFFLINE='1', THERMAL_TEST_ALLOWED_ROOT=str(output))
            env['PYTHONPATH'] = str(project / 'scripts/test_sandbox')
        details = {'mode': 'external_opt_in' if external else 'offline_isolated', 'workspace': str(project),
                   'copied_files': count, 'production_env_copied': False, 'source_resources_copied': resources,
                   'database': 'explicit environment' if external else 'held non-listening loopback port',
                   'thread_limit': 1, 'network_guard': not external, 'write_guard': not external}
        (output / 'isolation.json').write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')
        yield project, env, details
