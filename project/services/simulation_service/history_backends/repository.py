from __future__ import annotations

from .file_backend import FileHistoryBackend
from .memory import MemoryHistoryBackend
from .database import DatabaseHistoryBackend
from ..config import SimulationConfig


def build_history_backend(config: SimulationConfig):
    if config.history_backend == "database":
        return DatabaseHistoryBackend(
            database_url=config.history_database_url,
            enabled=config.history_database_enabled,
            auto_create=config.history_db_auto_create,
        )
    if config.history_backend == "file":
        return FileHistoryBackend(config.history_dir)
    return MemoryHistoryBackend()


__all__ = ["build_history_backend"]
