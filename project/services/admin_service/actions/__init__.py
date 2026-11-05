"""Static, bounded and read-only Admin Action Registry."""

from .service import ActionService, get_action_service

__all__ = ["ActionService", "get_action_service"]
