"""Compatibility wrapper for legacy start commands."""

from . import v11_api_server as _v11_api_server
from .v11_api_server import *  # noqa: F401,F403

__all__ = [*_v11_api_server.__all__]
