"""Dropbox OAuth 2.0 route handlers.

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

router = APIRouter(prefix="/api/v1/backup/dropbox", tags=["backup-dropbox"])

REDIRECT_URI = "http://127.0.0.1:18765/api/v1/backup/dropbox/callback"
AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

_state = OAuthStateStore()


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the Dropbox OAuth consent URL (offline access for refresh token)."""
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "dropbox"))
    config = result.scalar_one_or_none()
    client_id = settings.DROPBOX_CLIENT_ID
    stored = load_stored_credentials(config, "Dropbox")
    if stored.get("client_id"):
        client_id = stored["client_id"]
    if not client_id:
        raise HTTPException(status_code=400, detail="Dropbox OAuth client_id is not configured")

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "token_access_type": "offline",  # required to receive a refresh token
        "state": _state.issue(),
    }
    return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str = Query(...),
    state: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange the Dropbox auth code for tokens and save the config."""
    if not _state.consume(state):
        return error_page("Invalid or expired OAuth state. Please retry.")

    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "dropbox"))
    config = result.scalar_one_or_none()

    client_id = settings.DROPBOX_CLIENT_ID
    client_secret = settings.DROPBOX_CLIENT_SECRET
    stored = load_stored_credentials(config, "Dropbox")
    client_id = stored.get("client_id", client_id)
    client_secret = stored.get("client_secret", client_secret)
    if not client_id or not client_secret:
        return error_page("Dropbox client_id/client_secret are not configured")

    try:
        token_data = await exchange_authorization_code(
            TOKEN_URL,
            {
                "code": code,
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
            },
        )
    except Exception:
        logger.warning("Dropbox token exchange failed", exc_info=True)
        return error_page("Failed to connect to Dropbox. Please retry.")

    refresh_token = token_data.get("refresh_token") or stored.get("refresh_token")
    if not refresh_token:
        return error_page("No refresh token returned. Ensure the app uses long-lived access.")
    new_creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": token_data["access_token"],
        "refresh_token": refresh_token,
        "token_expiry": str(time.time() + token_data.get("expires_in", 14400)),
    }
    try:
        await upsert_backup_config(db, "dropbox", new_creds, existing=config)
    except Exception:
        logger.warning("Failed to persist Dropbox credentials", exc_info=True)
        return error_page("Failed to save the Dropbox connection. Please retry.")
    return success_page(
        "Dropbox Connected!",
        "✅",
        "LifeLogr is now connected to your Dropbox account.",
    )
