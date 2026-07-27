"""OneDrive (Microsoft Graph) OAuth 2.0 route handlers.

Exchange/upsert/render plumbing is shared via ``app.routers._oauth_helpers``.
"""

from __future__ import annotations

import json
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
from app.core.security import decrypt
from app.models.backup import BackupConfig
from app.routers._oauth_helpers import (
    error_page,
    exchange_authorization_code,
    success_page,
    upsert_backup_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backup/onedrive", tags=["backup-onedrive"])

REDIRECT_URI = "http://127.0.0.1:18765/api/v1/backup/onedrive/callback"
SCOPES = "Files.ReadWrite.AppFolder offline_access"
AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

_state = OAuthStateStore()


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the OneDrive OAuth consent URL."""
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "onedrive"))
    config = result.scalar_one_or_none()
    client_id = settings.ONEDRIVE_CLIENT_ID
    if config:
        try:
            client_id = json.loads(decrypt(config.credentials_encrypted)).get(
                "client_id", client_id
            )
        except Exception:
            logger.warning("Failed to decrypt stored OneDrive credentials", exc_info=True)
    if not client_id:
        raise HTTPException(status_code=400, detail="OneDrive OAuth client_id is not configured")

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "response_mode": "query",
        "scope": SCOPES,
        "state": _state.issue(),
    }
    return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str = Query(...),
    state: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange the OneDrive auth code for tokens and save the config."""
    if not _state.consume(state):
        return error_page("Invalid or expired OAuth state. Please retry.")

    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "onedrive"))
    config = result.scalar_one_or_none()

    client_id = settings.ONEDRIVE_CLIENT_ID
    client_secret = settings.ONEDRIVE_CLIENT_SECRET
    stored: dict[str, str] = {}
    if config:
        try:
            stored = json.loads(decrypt(config.credentials_encrypted))
            client_id = stored.get("client_id", client_id)
            client_secret = stored.get("client_secret", client_secret)
        except Exception:
            logger.warning("Failed to decrypt OneDrive credentials for token exchange", exc_info=True)
    if not client_id or not client_secret:
        return error_page("OneDrive client_id/client_secret are not configured")

    try:
        token_data = await exchange_authorization_code(
            TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "scope": SCOPES,
            },
        )
    except Exception:
        logger.warning("OneDrive token exchange failed", exc_info=True)
        return error_page("Failed to connect to OneDrive. Please retry.")

    refresh_token = token_data.get("refresh_token") or stored.get("refresh_token")
    if not refresh_token:
        return error_page("No refresh token returned. Please retry.")
    new_creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": token_data["access_token"],
        "refresh_token": refresh_token,
        "token_expiry": str(time.time() + token_data["expires_in"]),
    }
    try:
        await upsert_backup_config(db, "onedrive", new_creds, existing=config)
    except Exception:
        logger.warning("Failed to persist OneDrive credentials", exc_info=True)
        return error_page("Failed to save the OneDrive connection. Please retry.")
    return success_page(
        "OneDrive Connected!",
        "✅",
        "LifeLogr is now connected to your OneDrive account.",
    )
