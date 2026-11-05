from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import BinaryIO


CHUNK_SIZE = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_stream(stream: BinaryIO, *, rewind: bool = False) -> tuple[str, int]:
    digest = sha256()
    size = 0
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    if rewind and hasattr(stream, "seek"):
        stream.seek(0)
    return digest.hexdigest(), size


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as handle:
        return sha256_stream(handle)[0]


__all__ = ["CHUNK_SIZE", "sha256_bytes", "sha256_file", "sha256_stream"]
