"""Versioned OCR cache identity and non-destructive refresh writes."""
from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import shutil
import uuid

from services.retrieval_service.config import AppConfig


OCR_CACHE_VERSION = 'ocr-page-v2'


def _file_identity(path: Path) -> dict:
    if not path.is_file():
        return {'path': str(path), 'available': False}
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path.resolve()), 'available': True, 'sha256': digest.hexdigest()}


def _executable_identity(command: str) -> dict:
    resolved = shutil.which(command)
    return _file_identity(Path(resolved or command))


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def ocr_cache_profile(cfg: AppConfig, *, effective_tesseract_cmd: str) -> dict:
    engine = _executable_identity(effective_tesseract_cmd)
    language = cfg.ocr.lang or 'chi_sim+eng'
    # TESSDATA_PREFIX is used by the subprocess. Also retain the requested
    # config, which callers can construct without changing the environment.
    roots = list(dict.fromkeys(str(value) for value in (
        cfg.ocr.tessdata_dir, os.getenv('TESSDATA_PREFIX'),
        str(Path(engine['path']).parent / 'tessdata') if engine['available'] else None,
    ) if value))
    return {
        'schema_version': OCR_CACHE_VERSION,
        'language': language,
        'render_dpi': int(getattr(cfg.ocr, 'render_dpi', 300) or 300),
        'tesseract': engine,
        'poppler': {name: _executable_identity(name) for name in ('pdfinfo', 'pdftoppm')},
        'requested_tessdata_dir': cfg.ocr.tessdata_dir,
        'effective_tessdata_prefix': os.getenv('TESSDATA_PREFIX'),
        'traineddata': [_file_identity(Path(root) / f'{lang}.traineddata')
                        for root in roots for lang in language.split('+')],
        'packages': {name: _package_version(name) for name in ('pytesseract', 'pdf2image', 'Pillow')},
    }


def versioned_cache_dir(cfg: AppConfig, pdf_sha: str, *, effective_tesseract_cmd: str) -> Path:
    profile = ocr_cache_profile(cfg, effective_tesseract_cmd=effective_tesseract_cmd)
    serialized = json.dumps(profile, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    fingerprint = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    directory = cfg.paths.data_dir / 'ocr_cache' / pdf_sha / f'{OCR_CACHE_VERSION}-{fingerprint}'
    directory.mkdir(parents=True, exist_ok=True)
    metadata = directory / 'profile.json'
    if not metadata.exists():
        metadata.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
    # Unversioned page_*.txt under the parent are intentionally not read or
    # migrated: their OCR language, renderer and engine are unverified.
    return directory


def write_cached_page(path: Path, text: str) -> None:
    data = text.encode('utf-8')
    if path.exists():
        previous = path.read_bytes()
        if previous == data:
            return
        archive = path.with_name(f'{path.stem}.previous-{hashlib.sha256(previous).hexdigest()}.txt')
        if not archive.exists():
            archive.write_bytes(previous)
    temporary = path.with_name(f'{path.name}.{uuid.uuid4().hex}.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)
