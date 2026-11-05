from __future__ import annotations

from dataclasses import dataclass
import hmac
import ipaddress
import os
from threading import Lock
from time import monotonic

from fastapi import Header, Request

from .contracts import AdminAPIError


BASE_READ_PERMISSIONS = (
    "overview.read",
    "module.read",
    "module.check",
    "config.read",
    "audit.read",
)
READ_ONLY_PERMISSIONS = BASE_READ_PERMISSIONS + (
    "action.read",
    "action.dry_run",
    "action.execute.low",
)
CONFIG_WRITER_PERMISSIONS = BASE_READ_PERMISSIONS + ("config.write", "config.rollback")
WORKFLOW_WRITER_PERMISSIONS = READ_ONLY_PERMISSIONS + (
    "knowledge.upload",
    "knowledge.preflight",
    "knowledge.commit",
    "model.upload",
    "model.compile",
    "model.approve",
    "model.reject",
    "model.enable",
    "model.disable",
    "model.smoke",
    "model.rollback",
    "job.retry.safe",
)
LOCAL_ADMIN_PERMISSIONS = tuple(dict.fromkeys(WORKFLOW_WRITER_PERMISSIONS + CONFIG_WRITER_PERMISSIONS))
_RATE_LOCK = Lock()
_RATE_BUCKETS: dict[str, tuple[float, int]] = {}
_DEFAULT_ALLOWED_ORIGINS = frozenset(
    {
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://[::1]:4173",
        "http://[::1]:5173",
    }
)


@dataclass(frozen=True)
class AdminIdentity:
    actor_id: str = "phase-a-viewer"
    role: str = "viewer"
    permissions: tuple[str, ...] = READ_ONLY_PERMISSIONS
    auth_mode: str = "shared_token"
    read_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "role": self.role,
            "permissions": list(self.permissions),
            "auth_mode": self.auth_mode,
            "token_persistent": False,
            "read_only": self.read_only,
        }


def control_center_enabled() -> bool:
    return os.getenv("ADMIN_CONTROL_CENTER_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def local_admin_dev_mode_enabled() -> bool:
    return os.getenv("ADMIN_LOCAL_DEV_MODE_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def deployment_mode() -> str:
    return os.getenv("THERMALAGENT_DEPLOYMENT_MODE", "production").strip().lower() or "production"


def configured_admin_token() -> str:
    dedicated = os.getenv("ADMIN_CONTROL_CENTER_TOKEN", "").strip()
    if dedicated:
        return dedicated
    return os.getenv("ADMIN_FEATURE_FLAGS_TOKEN", "").strip()


def control_center_allowed_origins() -> frozenset[str]:
    raw = os.getenv("ADMIN_CONTROL_CENTER_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return _DEFAULT_ALLOWED_ORIGINS
    return frozenset(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


def require_admin_read_access(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> AdminIdentity:
    return _authenticate_read_access(request, x_admin_token, enforce_rate_limit=True)


def config_write_enabled() -> bool:
    return os.getenv("ADMIN_CONFIG_WRITE_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def configured_config_write_token() -> str:
    return os.getenv("ADMIN_CONFIG_WRITE_TOKEN", "").strip()


def workflow_write_enabled() -> bool:
    return os.getenv("ADMIN_WORKFLOW_WRITE_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on", "enabled",
    }


def configured_workflow_write_token() -> str:
    return os.getenv("ADMIN_WORKFLOW_WRITE_TOKEN", "").strip()


def require_admin_workflow_write_access(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_admin_workflow_token: str | None = Header(default=None, alias="X-Admin-Workflow-Token"),
) -> AdminIdentity:
    read_identity = _authenticate_read_access(request, x_admin_token, enforce_rate_limit=True)
    if read_identity.auth_mode == "local_development":
        return read_identity
    if not workflow_write_enabled():
        raise AdminAPIError("ADMIN_WORKFLOW_WRITE_DISABLED", "Admin workflow writes are disabled.", status_code=404)
    write_token = configured_workflow_write_token()
    if not write_token:
        raise AdminAPIError("ADMIN_WORKFLOW_WRITE_MISCONFIGURED", "Admin workflow write credential is not configured.", status_code=503)
    read_token = configured_admin_token()
    if read_token and hmac.compare_digest(read_token, write_token):
        raise AdminAPIError("ADMIN_WORKFLOW_WRITE_TOKEN_CONFLICT", "Admin read and workflow write credentials must be independent.", status_code=503)
    supplied = (x_admin_workflow_token or "").strip()
    if not supplied:
        raise AdminAPIError("ADMIN_WORKFLOW_WRITE_AUTH_REQUIRED", "An Admin workflow write credential is required.", status_code=401)
    if not hmac.compare_digest(supplied, write_token):
        raise AdminAPIError("ADMIN_WORKFLOW_WRITE_AUTH_INVALID", "The Admin workflow write credential is invalid.", status_code=401)
    return AdminIdentity(
        actor_id="admin-v1-workflow-operator",
        role="administrator",
        permissions=WORKFLOW_WRITER_PERMISSIONS,
        auth_mode="shared_workflow_write_token",
        read_only=False,
    )


def require_admin_config_write_access(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_admin_config_token: str | None = Header(default=None, alias="X-Admin-Config-Token"),
) -> AdminIdentity:
    read_identity = _authenticate_read_access(request, x_admin_token, enforce_rate_limit=True)
    if read_identity.auth_mode == "local_development":
        return read_identity
    if not config_write_enabled():
        raise AdminAPIError(
            "ADMIN_CONFIG_WRITE_DISABLED",
            "Config Registry writes are disabled.",
            status_code=404,
        )
    write_token = configured_config_write_token()
    if not write_token:
        raise AdminAPIError(
            "ADMIN_CONFIG_WRITE_MISCONFIGURED",
            "Config Registry has no server-side write credential configured.",
            status_code=503,
        )
    read_token = configured_admin_token()
    if read_token and hmac.compare_digest(read_token, write_token):
        raise AdminAPIError(
            "ADMIN_CONFIG_WRITE_TOKEN_CONFLICT",
            "Config Registry read and write credentials must be independent.",
            status_code=503,
        )
    supplied = (x_admin_config_token or "").strip()
    if not supplied:
        raise AdminAPIError(
            "ADMIN_CONFIG_WRITE_AUTH_REQUIRED",
            "A Config Registry write credential is required.",
            status_code=401,
        )
    if not hmac.compare_digest(supplied, write_token):
        raise AdminAPIError(
            "ADMIN_CONFIG_WRITE_AUTH_INVALID",
            "The Config Registry write credential is invalid.",
            status_code=401,
        )
    return AdminIdentity(
        actor_id="phase-b1-config-writer",
        role="administrator",
        permissions=CONFIG_WRITER_PERMISSIONS,
        auth_mode="shared_config_write_token",
        read_only=False,
    )


def _authenticate_read_access(
    request: Request,
    x_admin_token: str | None,
    *,
    enforce_rate_limit: bool,
) -> AdminIdentity:
    local_identity = _local_development_identity(request, x_admin_token)
    if local_identity is not None:
        if enforce_rate_limit:
            _enforce_rate_limit(request)
        return local_identity
    if not control_center_enabled():
        raise AdminAPIError(
            "ADMIN_API_DISABLED",
            "Admin Control Center is disabled.",
            status_code=404,
        )
    expected = configured_admin_token()
    if not expected:
        raise AdminAPIError(
            "ADMIN_API_MISCONFIGURED",
            "Admin Control Center has no server-side token configured.",
            status_code=503,
        )
    supplied = (x_admin_token or "").strip()
    if not supplied:
        raise AdminAPIError("AUTH_REQUIRED", "Admin authentication is required.", status_code=401)
    if not hmac.compare_digest(supplied, expected):
        raise AdminAPIError("AUTH_INVALID", "Admin authentication is invalid.", status_code=401)
    origin = request.headers.get("origin", "").strip().rstrip("/")
    if origin and origin not in control_center_allowed_origins():
        raise AdminAPIError(
            "ORIGIN_FORBIDDEN",
            "Admin request origin is not allowed.",
            status_code=403,
        )
    if enforce_rate_limit:
        _enforce_rate_limit(request)
    return AdminIdentity()


def _local_development_identity(request: Request, supplied_token: str | None) -> AdminIdentity | None:
    if not local_admin_dev_mode_enabled() or deployment_mode() not in {"development", "dev", "local"}:
        return None
    if not _is_loopback_host(request.client.host if request.client else ""):
        if not (supplied_token or "").strip():
            raise AdminAPIError(
                "LOCAL_ADMIN_LOOPBACK_REQUIRED",
                "Local Admin development access is restricted to the loopback interface.",
                status_code=403,
            )
        return None
    origin = request.headers.get("origin", "").strip().rstrip("/")
    if origin and origin not in control_center_allowed_origins():
        raise AdminAPIError(
            "ORIGIN_FORBIDDEN",
            "Admin request origin is not allowed.",
            status_code=403,
        )
    return AdminIdentity(
        actor_id="local-admin-development",
        role="administrator",
        permissions=LOCAL_ADMIN_PERMISSIONS,
        auth_mode="local_development",
        read_only=False,
    )


def _is_loopback_host(value: str) -> bool:
    host = str(value or "").strip().lower().strip("[]")
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def _enforce_rate_limit(request: Request) -> None:
    try:
        limit = int(os.getenv("ADMIN_CONTROL_CENTER_RATE_LIMIT_PER_MINUTE", "120"))
    except ValueError:
        limit = 120
    limit = max(10, min(limit, 600))
    client = request.client.host if request.client else "unknown"
    now = monotonic()
    with _RATE_LOCK:
        started, count = _RATE_BUCKETS.get(client, (now, 0))
        if now - started >= 60:
            started, count = now, 0
        if count >= limit:
            raise AdminAPIError(
                "RATE_LIMITED",
                "Admin read request rate limit was exceeded.",
                status_code=429,
                retryable=True,
            )
        _RATE_BUCKETS[client] = (started, count + 1)
        if len(_RATE_BUCKETS) > 2048:
            expired = [key for key, (window, _value) in _RATE_BUCKETS.items() if now - window >= 60]
            for key in expired:
                _RATE_BUCKETS.pop(key, None)


def reset_admin_rate_limits_for_tests() -> None:
    with _RATE_LOCK:
        _RATE_BUCKETS.clear()


__all__ = [
    "AdminIdentity",
    "BASE_READ_PERMISSIONS",
    "CONFIG_WRITER_PERMISSIONS",
    "READ_ONLY_PERMISSIONS",
    "WORKFLOW_WRITER_PERMISSIONS",
    "LOCAL_ADMIN_PERMISSIONS",
    "configured_admin_token",
    "configured_config_write_token",
    "configured_workflow_write_token",
    "config_write_enabled",
    "control_center_allowed_origins",
    "control_center_enabled",
    "deployment_mode",
    "local_admin_dev_mode_enabled",
    "require_admin_read_access",
    "require_admin_config_write_access",
    "require_admin_workflow_write_access",
    "reset_admin_rate_limits_for_tests",
    "workflow_write_enabled",
]
