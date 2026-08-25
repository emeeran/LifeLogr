"""Box OAuth 2.0 route handlers — mirrors google_drive.py.

Loopback flow: /auth-url builds the Box consent URL; Box redirects to
REDIRECT_URI (port 18765), /callback exchanges the code for tokens and upserts
a BackupConfig(provider="box"). Box rotates its refresh token, so the stored
creds are rewritten whenever BackupService refreshes (see BoxProvider).

Exchange/upsert/render plumbing is shared via ``app.routers._oauth_helpers``.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import OAuthStateStore
from app.models.backup import BackupConfig
from app.routers._oauth_helpers import (
    error_page,
    exchange_authorization_code,
    load_stored_credentials,
    success_page,
    upsert_backup_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backup/box", tags=["backup-box"])

AUTHORIZE_URL = "https://account.box.com/api/oauth2/authorize"
TOKEN_URL = "https://api.box.com/oauth2/token"
REDIRECT_URI = "http://localhost:18765/api/v1/backup/box/callback"
_state = OAuthStateStore()


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the Box OAuth consent screen URL."""
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "box"))
    config = result.scalar_one_or_none()

    client_id = settings.BOX_CLIENT_ID
    stored = load_stored_credentials(config, "Box")
    if stored.get("client_id"):
        client_id = stored["client_id"]

    if not client_id:
        raise HTTPException(status_code=400, detail="Box OAuth client_id is not configured")

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": _state.issue(),
    }
    return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str | None = Query(None, description="Authorization code from Box"),
    state: str | None = Query(None, description="OAuth state token"),
    error: str | None = Query(None, description="OAuth error from Box"),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle the Box OAuth loopback redirect: exchange code, save tokens."""
    if error:
        msg = f"Box denied the request: {error}"
        if error_description:
            msg += f" — {error_description}"
        return error_page(msg)
    if not code:
        return error_page("Box returned no authorization code.")
    if not _state.consume(state):
        return error_page("Invalid or expired OAuth state. Please retry connection.")

    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "box"))
    config = result.scalar_one_or_none()

    client_id = settings.BOX_CLIENT_ID
    client_secret = settings.BOX_CLIENT_SECRET
    stored = load_stored_credentials(config, "Box")
    client_id = stored.get("client_id") or client_id
    client_secret = stored.get("client_secret") or client_secret

    if not client_id or not client_secret:
        return error_page("Box OAuth client_id/client_secret are not configured")

    try:
        tokens = await exchange_authorization_code(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=15.0,
        )
    except Exception:
        logger.warning("Box token exchange failed", exc_info=True)
        return error_page("Failed to connect to Box. Please retry.")

    if not tokens.get("refresh_token"):
        return error_page("No refresh token returned by Box. Please retry.")

    new_creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_expiry": str(time.time() + tokens["expires_in"]),
    }
    try:
        await upsert_backup_config(db, "box", new_creds, existing=config)
    except Exception:
        logger.warning("Failed to persist Box credentials", exc_info=True)
        return error_page("Failed to save the Box connection. Please retry.")

    return success_page("Box Connected!", "📦", "LifeLogr is now connected to your Box account.")
