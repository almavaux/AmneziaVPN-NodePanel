import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..auth import require_api_key
from ...core.awg_manager import (
    create_user,
    delete_user,
    get_user_config,
    get_user_qr,
    list_users,
)
from ...core.models import UserCreate, UserCreateResponse, UserListItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])
_Auth = Annotated[str, Depends(require_api_key)]


# ---------------------------------------------------------------------------
# base64url helpers (RFC 4648 §5)
# URL path segments cannot contain '/' (+/= are problematic), so we use
# base64url (- and _ instead of + and /) without padding.
# ---------------------------------------------------------------------------

def _to_b64url(b64: str) -> str:
    """Standard base64 → base64url (no padding)."""
    return b64.replace("+", "-").replace("/", "_").rstrip("=")


def _from_b64url(b64url: str) -> str:
    """base64url → standard base64 with padding restored."""
    b64 = b64url.replace("-", "+").replace("_", "/")
    pad = (4 - len(b64) % 4) % 4
    return b64 + "=" * pad


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------

@router.get("", response_model=list[UserListItem])
def api_list_users(auth: _Auth) -> list[UserListItem]:
    """List all peers with their name, IP, and live transfer stats."""
    try:
        users = list_users()
    except Exception as exc:
        logger.exception("list_users failed")
        raise HTTPException(status_code=500, detail=str(exc))
    # Convert client_id to base64url for safe URL path use
    for u in users:
        u.client_id = _to_b64url(u.client_id)
    return users


# ---------------------------------------------------------------------------
# POST /users
# ---------------------------------------------------------------------------

@router.post("", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
def api_create_user(body: UserCreate, auth: _Auth) -> UserCreateResponse:
    """
    Create a new AWG peer.

    Returns the user metadata and an Amnezia-compatible vpn:// link.
    To get the QR code, call GET /users/{client_id}/qr afterwards.
    """
    try:
        user, config_str, _ = create_user(body)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("create_user failed")
        raise HTTPException(status_code=500, detail=str(exc))

    return UserCreateResponse(
        user=user.model_copy(update={"client_id": _to_b64url(user.client_id)}),
        config=config_str,
    )


# ---------------------------------------------------------------------------
# DELETE /users/{client_id}
# ---------------------------------------------------------------------------

@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_user(client_id: str, auth: _Auth) -> None:
    """Remove an AWG peer by its public key (clientId)."""
    try:
        found = delete_user(_from_b64url(client_id))
    except Exception as exc:
        logger.exception("delete_user failed")
        raise HTTPException(status_code=500, detail=str(exc))

    if not found:
        raise HTTPException(status_code=404, detail="User not found")


# ---------------------------------------------------------------------------
# GET /users/{client_id}/config
# ---------------------------------------------------------------------------

@router.get("/{client_id}/config", response_class=Response)
def api_get_config(client_id: str, auth: _Auth) -> Response:
    """Download Amnezia-compatible vpn:// link as a text file (.vpn)."""
    try:
        config = get_user_config(_from_b64url(client_id))
    except Exception as exc:
        logger.exception("get_user_config failed")
        raise HTTPException(status_code=500, detail=str(exc))

    if config is None:
        raise HTTPException(status_code=404, detail="User not found or private key unavailable")

    return Response(
        content=config,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{client_id[:8]}.vpn"'},
    )


# ---------------------------------------------------------------------------
# GET /users/{client_id}/qr
# ---------------------------------------------------------------------------

@router.get("/{client_id}/qr", response_class=Response)
def api_get_qr(client_id: str, auth: _Auth) -> Response:
    """Return Amnezia-compatible vpn:// link as a QR code PNG image."""
    try:
        png = get_user_qr(_from_b64url(client_id))
    except Exception as exc:
        logger.exception("get_user_qr failed")
        raise HTTPException(status_code=500, detail=str(exc))

    if png is None:
        raise HTTPException(status_code=404, detail="User not found or private key unavailable")

    return Response(content=png, media_type="image/png")
