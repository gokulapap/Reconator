import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Header-based API key gate for mutating endpoints.

    When ADMIN_API_KEY is unset, the gate is open (suitable for local/dev).
    When set, requests must send X-API-Key matching the configured value.
    """
    if not settings.auth_enabled:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.admin_api_key or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


async def require_read_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Protect reconnaissance intelligence reads when configured.

    Development remains convenient by default. Production Compose enables this
    guard because assets, evidence, raw output, and scan history are sensitive.
    """
    if not settings.protect_read_endpoints:
        return
    await require_api_key(x_api_key)
