"""Artifact hashing and Unicode-safe FAISS file I/O; optional imports are lazy."""
from hashlib import sha256
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_faiss_index(path: str | Path):
    """Use Python file I/O so Windows C stdio never receives a Unicode path."""
    import faiss
    import numpy as np

    serialized = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    return faiss.deserialize_index(serialized)


def write_faiss_index(index, path: str | Path) -> None:
    """Persist FAISS's standard format, usable by native FAISS readers too."""
    import faiss

    with Path(path).open('wb') as handle:
        handle.write(memoryview(faiss.serialize_index(index)))

