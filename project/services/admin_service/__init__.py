"""Read-only ThermalAgent Control Center service (Phase A)."""

from .api import install_admin_api, router

__all__ = ["install_admin_api", "router"]
