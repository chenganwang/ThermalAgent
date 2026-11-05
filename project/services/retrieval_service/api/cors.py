"""Explicit browser origins for the local engineering API."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_ORIGINS = tuple(f"http://{host}:{port}" for host in ("127.0.0.1", "localhost", "[::1]") for port in (5173, 4173))


def allowed_origins() -> list[str]:
    raw = os.getenv("RAG_CORS_ALLOWED_ORIGINS")
    if raw is None:
        return list(DEFAULT_ORIGINS)
    origins = []
    for value in raw.split(","):
        value = value.strip()
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                continue
            _ = parsed.port
        except ValueError:
            continue
        if value not in origins:
            origins.append(value)
    return origins
