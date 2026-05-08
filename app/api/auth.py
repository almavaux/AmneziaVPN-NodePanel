from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from starlette.requests import Request

from ..core.config import settings, get_allowed_ip_set

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def require_api_key(request: Request, key: str = Security(_api_key_header)) -> str:
    allowed = get_allowed_ip_set()
    if allowed:
        # If API is behind local reverse proxy, use forwarded real client IP.
        forwarded = request.headers.get("x-real-ip", "")
        client_ip = forwarded.split(",", 1)[0].strip() if forwarded else ""
        if not client_ip:
            client_ip = request.client.host if request.client else ""
        if client_ip not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caller IP is not allowed",
            )

    if key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return key
