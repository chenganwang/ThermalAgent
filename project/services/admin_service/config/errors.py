from __future__ import annotations

from typing import Any

from ..contracts import AdminAPIError


class ConfigRegistryError(AdminAPIError):
    """Stable Admin API error raised by the controlled Config Registry."""


def config_error(
    code: str,
    message: str,
    *,
    status_code: int,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> ConfigRegistryError:
    return ConfigRegistryError(
        code,
        message,
        status_code=status_code,
        details=details,
        retryable=retryable,
    )


__all__ = ["ConfigRegistryError", "config_error"]
