"""Google Drive OAuth 2.0 route handlers."""

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

router = APIRouter(prefix="/api/v1/backup/google-drive", tags=["backup-google-drive"])

REDIRECT_URI = "http://127.0.0.1:18765/api/v1/backup/google-drive/callback"
_state = OAuthStateStore()


def get_default_credentials() -> tuple[str, str]:
    return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate Google Drive OAuth consent screen URL."""
    # Look for existing custom client config in database
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_drive"))
    config = result.scalar_one_or_none()

    default_id, _ = get_default_credentials()
    client_id = default_id
    stored = load_stored_credentials(config, "Google")
    if stored.get("client_id"):
        client_id = stored["client_id"]

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth client_id is not configured",
        )

    # drive.file: create/access the visible "LifeLogr Backups" folder.
    # drive.appdata: retained so older hidden backups can be migrated out.
    scopes = (
        "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.appdata"
    )
    auth_base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    state = _state.issue()

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    return {"auth_url": f"{auth_base_url}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str | None = Query(None, description="OAuth state token"),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle Google OAuth 2.0 loopback redirection, exchange code, and save tokens."""
    if not _state.consume(state):
        return error_page("Invalid or expired OAuth state. Please retry connection.")

    # 1. Resolve client credentials
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_drive"))
    config = result.scalar_one_or_none()

    default_id, default_secret = get_default_credentials()
    client_id = default_id
    client_secret = default_secret

    stored = load_stored_credentials(config, "Google")
    client_id = stored.get("client_id") or client_id
    client_secret = stored.get("client_secret") or client_secret

    if not client_id or not client_secret:
        return error_page("Google OAuth client_id/client_secret are not configured")

    # 2. Exchange authorization code for tokens (shared helper).
    try:
        token_data = await exchange_authorization_code(
            "https://oauth2.googleapis.com/token",
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    except Exception:
        logger.warning("Google Drive token exchange failed", exc_info=True)
        return error_page("Failed to connect to Google Drive. Please retry.")

    # 3. Encrypt and save configuration in DB (shared helper).
    refresh_token = token_data.get("refresh_token") or (
        stored.get("refresh_token") if config else None
    )
    if not refresh_token:
        # prompt=consent didn't fire / first-time sync — ask the user to retry.
        return error_page("No refresh token returned. Please disconnect and try again.")

    new_creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": token_data["access_token"],
        "refresh_token": refresh_token,
        "token_expiry": str(time.time() + token_data["expires_in"]),
    }
    try:
        await upsert_backup_config(db, "google_drive", new_creds, existing=config)
    except Exception:
        logger.warning("Failed to persist Google Drive credentials", exc_info=True)
        return error_page("Failed to save the Google Drive connection. Please retry.")

    # 4. Render success page.
    return success_page(
        "Google Drive Connected!",
        "🎉",
        "LifeLogr is now connected to your Google Drive account.",
    )
